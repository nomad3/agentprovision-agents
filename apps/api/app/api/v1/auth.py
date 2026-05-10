from datetime import timedelta, datetime
import hashlib
import hmac
import json
import secrets
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.schemas import token as token_schema
from app.schemas import user as user_schema
from app.schemas import tenant as tenant_schema
from app.schemas import auth as auth_schema
from app.api import deps
from app.core import security
from app.core.config import settings
from app.services import base as base_service
from app.services import users as user_service
from app.core.rate_limit import limiter

router = APIRouter()
logger = logging.getLogger(__name__)

_PASSWORD_RESET_MESSAGE = "Password reset instructions sent if email is registered"

# Cap the refresh chain. Even with /auth/refresh, the *original* iat travels
# with every refreshed token, so a stolen token at hour 0 can be refreshed
# at most until hour `MAX_TOKEN_CHAIN_AGE_SECONDS / 3600`. After that the
# user must re-authenticate. 7 days = weekly forced re-auth.
MAX_TOKEN_CHAIN_AGE_SECONDS = 7 * 24 * 60 * 60


@router.post("/login", response_model=token_schema.Token)
@limiter.limit("10/minute")
def login_for_access_token(
    request: Request,
    db: Session = Depends(deps.get_db), form_data: OAuth2PasswordRequestForm = Depends()
):
    user = base_service.authenticate_user(db, email=form_data.username, password=form_data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = {"user_id": str(user.id)}
    if user.tenant_id:
        claims["tenant_id"] = str(user.tenant_id)

    access_token = security.create_access_token(
        user.email,
        expires_delta=access_token_expires,
        additional_claims=claims,
    )
    return {"access_token": access_token, "token_type": "bearer"}


def _bearer_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


@router.post("/refresh", response_model=token_schema.Token)
@limiter.limit("60/minute")
def refresh_access_token(
    request: Request,
    current_user=Depends(deps.get_current_active_user),
):
    """Re-issue a fresh access token for the currently authenticated caller.

    The caller must present a still-valid bearer token. We re-mint with the
    same identity claims, a fresh `exp`, and the *original* `iat` preserved
    so the refresh chain has a bounded lifetime. After
    `MAX_TOKEN_CHAIN_AGE_SECONDS` since original login, the user must
    re-authenticate.
    """
    raw_token = _bearer_token(request)
    original_iat: int | None = None
    if raw_token:
        try:
            decoded = jwt.decode(
                raw_token,
                settings.SECRET_KEY,
                algorithms=[security.ALGORITHM],
            )
            iat_claim = decoded.get("iat")
            if isinstance(iat_claim, (int, float)):
                original_iat = int(iat_claim)
        except JWTError:
            # Token failed to decode — get_current_active_user already
            # rejected this case, so we shouldn't get here. Fall through
            # to a fresh iat to avoid hard-failing the refresh on an
            # encoding edge case.
            original_iat = None

    if original_iat is not None:
        age = int(time.time()) - original_iat
        if age > MAX_TOKEN_CHAIN_AGE_SECONDS:
            raise HTTPException(
                status_code=401,
                detail="session too old; please re-authenticate",
                headers={"WWW-Authenticate": "Bearer"},
            )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = {"user_id": str(current_user.id)}
    if current_user.tenant_id:
        claims["tenant_id"] = str(current_user.tenant_id)
    access_token = security.create_access_token(
        current_user.email,
        expires_delta=access_token_expires,
        additional_claims=claims,
        iat=original_iat,
    )
    logger.info("Token refreshed for %s", current_user.email)
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", response_model=user_schema.User)
def register_user(
    *,
    db: Session = Depends(deps.get_db),
    user_in: user_schema.UserCreate,
    tenant_in: tenant_schema.TenantCreate
):
    user = user_service.get_user_by_email(db, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    user = user_service.create_user_with_tenant(db, user_in=user_in, tenant_in=tenant_in)
    return user

@router.get("/users/me", response_model=user_schema.User)
def read_users_me(
    current_user: user_schema.User = Depends(deps.get_current_active_user)
):
    """
    Get current user.
    """
    return current_user

@router.post("/password-recovery/{email}")
@limiter.limit("3/hour")
def recover_password(request: Request, email: str, db: Session = Depends(deps.get_db)):
    """
    Password recovery
    """
    user = user_service.get_user_by_email(db, email=email)

    if not user:
        # Identical message for missing user — prevents email enumeration
        return {"message": _PASSWORD_RESET_MESSAGE}

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    user.password_reset_token = token_hash
    user.password_reset_expires = datetime.utcnow() + timedelta(hours=24)
    db.add(user)
    db.commit()

    # In a real app, send an email here. For now, log it.
    logger.info(f"Password reset token generated for {email}")

    return {"message": _PASSWORD_RESET_MESSAGE}

@router.post("/reset-password")
@limiter.limit("5/hour")
def reset_password(
    request: Request,
    body: auth_schema.PasswordResetConfirm,
    db: Session = Depends(deps.get_db)
):
    """
    Reset password
    """
    user = user_service.get_user_by_email(db, email=body.email)

    if not user or not user.password_reset_token or not user.password_reset_expires:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    if user.password_reset_expires < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    submitted_hash = hashlib.sha256(body.token.encode()).hexdigest()
    if not hmac.compare_digest(user.password_reset_token, submitted_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    user.hashed_password = security.get_password_hash(body.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    db.add(user)
    db.commit()

    return {"message": "Password updated successfully"}


# ---------------------------------------------------------------------------
# Device-flow login (gh-style) for the `agentprovision` CLI
# ---------------------------------------------------------------------------
#
# Flow:
#   1. Client POST /api/v1/auth/device-code  -> returns { device_code, user_code, verification_uri, expires_in, interval }
#   2. User opens verification_uri in a browser, authenticates with the
#      existing /login page, and POSTs /api/v1/auth/device-approve { user_code }
#      while logged in to bind their access_token to the device_code.
#   3. Client polls POST /api/v1/auth/device-token { device_code }
#      -> 200 { access_token, token_type } once approved
#      -> 400 { error: "authorization_pending" | "slow_down" | "expired_token" | "access_denied" }
#
# Pending state is stored in Redis with a short TTL. If Redis is unavailable
# we fail closed (CLI falls back to email/password prompts).

from pydantic import BaseModel, Field

_DEVICE_CODE_TTL_SECONDS = 600  # 10 minutes
_DEVICE_CODE_INTERVAL_SECONDS = 5
_DEVICE_USER_CODE_LEN = 8  # Pretty-printed as XXXX-XXXX


class DeviceCodeResponse(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class DeviceApproveRequest(BaseModel):
    user_code: str = Field(
        ...,
        description="The XXXX-XXXX code the user typed in the browser",
        min_length=8,
        max_length=10,
    )


class DeviceApproveResponse(BaseModel):
    approved: bool


class DeviceTokenRequest(BaseModel):
    device_code: str = Field(..., description="Opaque token issued by /device-code")


class DeviceTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

# Treat 'I', 'O', '0', '1' as ambiguous; pick a friendly alphabet.
_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _device_redis():
    try:
        import redis as redis_lib
        return redis_lib.from_url(settings.REDIS_URL)
    except Exception as exc:
        logger.warning("auth.device-code: redis unavailable: %s", exc)
        return None


def _generate_user_code() -> str:
    raw = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(_DEVICE_USER_CODE_LEN))
    return f"{raw[:4]}-{raw[4:]}"


def _device_state_key(device_code: str) -> str:
    return f"auth:device:{device_code}"


def _user_code_index_key(user_code: str) -> str:
    return f"auth:device:user:{user_code}"


@router.post("/device-code", response_model=DeviceCodeResponse)
@limiter.limit("20/minute")
def request_device_code(request: Request) -> DeviceCodeResponse:
    """Mint a new device_code + user_code pair (gh-style device-flow). No auth required.

    The CLI calls this first, opens ``verification_uri_complete`` in a browser,
    and then polls ``POST /device-token`` with the returned ``device_code``
    until the user approves in the web UI.
    """
    redis = _device_redis()
    if redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="device-flow login unavailable (cache backend down)",
        )
    device_code = secrets.token_urlsafe(32)
    user_code = _generate_user_code()
    base_url = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    verification_uri = f"{base_url}/login/device" if base_url else "/login/device"
    verification_uri_complete = f"{verification_uri}?user_code={user_code}"
    state = json.dumps({
        "user_code": user_code,
        "status": "pending",
        "access_token": None,
    })
    try:
        redis.set(_device_state_key(device_code), state, ex=_DEVICE_CODE_TTL_SECONDS)
        redis.set(_user_code_index_key(user_code), device_code, ex=_DEVICE_CODE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("auth.device-code: redis write failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="device-flow login unavailable",
        )
    return DeviceCodeResponse(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=verification_uri_complete,
        expires_in=_DEVICE_CODE_TTL_SECONDS,
        interval=_DEVICE_CODE_INTERVAL_SECONDS,
    )


@router.post("/device-approve", response_model=DeviceApproveResponse)
@limiter.limit("10/minute")
def approve_device_code(
    request: Request,
    body: DeviceApproveRequest,
    current_user=Depends(deps.get_current_active_user),
) -> DeviceApproveResponse:
    """Web UI calls this once the logged-in user enters the user_code they got
    from the CLI. Binds a fresh access token to the device_code so the CLI's
    next ``/device-token`` poll succeeds.

    Strips dashes + whitespace from the user_code before lookup so paste-from-
    screenshot users (extra spaces) and dashless typers ("ABCDEFGH" instead of
    "ABCD-EFGH") both work. Stored canonically as XXXX-XXXX uppercase.

    Refuses to re-bind an already-approved device_code (409) — closes the
    TOCTOU window where a second logged-in user could swap the bound token
    on a polling CLI at the last millisecond. Phase 4 review C-2.
    """
    # Normalise: strip whitespace, drop dashes, uppercase, then re-insert the
    # canonical dash. Accepts "ABCD-EFGH", "abcd-efgh", "ABCDEFGH", "abcdefgh",
    # "AB CD-EF GH", etc.
    raw_uc = "".join(body.user_code.split()).replace("-", "").upper()
    if len(raw_uc) != _DEVICE_USER_CODE_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"user_code must be {_DEVICE_USER_CODE_LEN} characters (XXXX-XXXX)",
        )
    user_code = f"{raw_uc[:4]}-{raw_uc[4:]}"
    redis = _device_redis()
    if redis is None:
        raise HTTPException(status_code=503, detail="device-flow login unavailable")
    raw_dc = redis.get(_user_code_index_key(user_code))
    if not raw_dc:
        raise HTTPException(status_code=404, detail="user_code not found or expired")
    device_code = raw_dc.decode() if isinstance(raw_dc, (bytes, bytearray)) else raw_dc
    raw = redis.get(_device_state_key(device_code))
    if not raw:
        raise HTTPException(status_code=404, detail="device_code expired")
    state = json.loads(raw)
    if state.get("status") == "approved":
        # Already bound — refuse to overwrite with a different user's token.
        raise HTTPException(status_code=409, detail="device_code already approved")
    # Mint a token for the approving user.
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = {"user_id": str(current_user.id)}
    if current_user.tenant_id:
        claims["tenant_id"] = str(current_user.tenant_id)
    access_token = security.create_access_token(
        current_user.email,
        expires_delta=access_token_expires,
        additional_claims=claims,
    )
    state["status"] = "approved"
    state["access_token"] = access_token
    redis.set(_device_state_key(device_code), json.dumps(state), ex=_DEVICE_CODE_TTL_SECONDS)
    return DeviceApproveResponse(approved=True)


def _device_error(error_code: str, http_status: int = 400) -> JSONResponse:
    """RFC-8628 error response with the error code at the TOP LEVEL of the
    body — NOT under FastAPI's default `detail` envelope. The Rust CLI client
    in apps/agentprovision-core/src/auth.rs deserializes `body.error` flat;
    any `{"detail": {"error": "..."}}` shape would deserialize to None and
    break every poll. Phase 4 review C-1.
    """
    return JSONResponse(status_code=http_status, content={"error": error_code})


@router.post(
    "/device-token",
    responses={
        200: {"model": DeviceTokenResponse},
        400: {"description": "RFC-8628 error: authorization_pending | slow_down | expired_token | access_denied | invalid_request"},
        503: {"description": "Cache backend unavailable"},
    },
)
@limiter.limit("60/minute")
def poll_device_token(request: Request, body: DeviceTokenRequest):
    """CLI polls this with the device_code. Mirrors GitHub's RFC-8628 wire model:
    400 + {"error": "authorization_pending" | "slow_down" | "expired_token" |
    "access_denied" | "invalid_request"} at the TOP LEVEL of the body so
    gh-style polling clients (incl. apps/agentprovision-core/src/auth.rs)
    deserialize the error code without unwrapping nested envelopes.
    """
    device_code = body.device_code.strip()
    if not device_code:
        return _device_error("invalid_request")
    redis = _device_redis()
    if redis is None:
        raise HTTPException(status_code=503, detail="device-flow login unavailable")
    raw = redis.get(_device_state_key(device_code))
    if not raw:
        # No record -> expired or never minted.
        return _device_error("expired_token")
    state = json.loads(raw)
    status_field = state.get("status")
    if status_field == "pending":
        return _device_error("authorization_pending")
    if status_field == "denied":
        return _device_error("access_denied")
    if status_field == "approved":
        token = state.get("access_token")
        if not token:
            # Race / corrupted state — treat as expired so the CLI re-bootstraps.
            return _device_error("expired_token")
        # One-shot: consume the device_code on first successful poll so a leaked
        # token in transit can't be replayed AND two parallel polls can't
        # double-issue. Use Redis GETDEL (atomic) so the read+delete is one
        # round-trip — a parallel poll either wins the GETDEL and gets the
        # token, or sees the key already gone and returns expired_token.
        # Phase 4 review I-1.
        try:
            atomic = redis.getdel(_device_state_key(device_code))
            if atomic is None:
                # Lost the race to a parallel poll — let the winner have the
                # token, return expired here.
                return _device_error("expired_token")
            user_code = state.get("user_code")
            if user_code:
                redis.delete(_user_code_index_key(user_code))
        except AttributeError:
            # Older redis-py without getdel — fall back to delete (still
            # one-shot under non-concurrent load, which is the realistic
            # case for a CLI polling at 5s intervals).
            try:
                redis.delete(_device_state_key(device_code))
                user_code = state.get("user_code")
                if user_code:
                    redis.delete(_user_code_index_key(user_code))
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            # Best-effort cleanup; the TTL on the keys is the backstop.
            pass
        return DeviceTokenResponse(access_token=token, token_type="bearer")
    return _device_error("expired_token")
