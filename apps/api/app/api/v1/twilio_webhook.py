"""Twilio inbound SMS webhook handler.

Receives inbound SMS messages from Twilio's `Messaging Webhook` (configured
on each tenant's Twilio phone number to POST to
`https://<public-host>/api/v1/integrations/twilio/inbound`).

Flow:
  1. Verify the X-Twilio-Signature header (HMAC-SHA1 over the canonical
     request URL + sorted form params, using the tenant's auth_token as the
     key). Twilio publishes the algorithm at
     https://www.twilio.com/docs/usage/security#validating-requests
  2. Resolve tenant_id from the `To` number — match against
     IntegrationCredential rows where credential_key='phone_number' under an
     active twilio_sms integration_config.
  3. Resolve / create a ChatSession keyed on
     (tenant_id, source='twilio_sms', external_id=f"twilio_sms:{From}").
  4. Pick the Pet Health Concierge agent if present, otherwise the tenant's
     primary agent.
  5. Dispatch through chat_service.post_user_message in a thread pool so the
     synchronous CLI orchestrator path works; capture the assistant's reply
     content before crossing the thread boundary.
  6. POST a Twilio outbound `Messages.json` request from the resolved
     tenant's account_sid+auth_token to deliver the response.
  7. Log inbound + outbound to channel_events for the audit trail.

Apple Messages for Business (iMessage) is intentionally NOT implemented here
— that path requires Apple Business Register approval (4-12 weeks). See the
"iMessage roadmap" section of `docs/plans/2026-05-09-imessage-sms-integration.md`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.agent import Agent
from app.models.channel_account import ChannelAccount
from app.models.channel_event import ChannelEvent
from app.models.chat import ChatSession
from app.models.integration_config import IntegrationConfig
from app.models.user import User
from app.services.orchestration.credential_vault import retrieve_credentials_for_skill

logger = logging.getLogger(__name__)

router = APIRouter()


TWILIO_INTEGRATION_NAME = "twilio_sms"

# When True, the webhook accepts unsigned requests. Default False — production
# must always require a valid signature. Tests flip this off and pass a real
# signature; integration smoke tests can set it true.
def _signature_required() -> bool:
    return os.environ.get("TWILIO_SKIP_SIGNATURE_CHECK", "").lower() not in {"1", "true", "yes"}


def _normalize_phone(value: str | None) -> str:
    """Strip everything except digits and a leading '+'."""
    if not value:
        return ""
    value = value.strip()
    if value.startswith("+"):
        return "+" + "".join(ch for ch in value[1:] if ch.isdigit())
    return "".join(ch for ch in value if ch.isdigit())


# ---------------------------------------------------------------------------
# Tenant + agent resolution
# ---------------------------------------------------------------------------

def _resolve_tenant_for_to_number(db: Session, to_number: str) -> Optional[tuple[uuid.UUID, IntegrationConfig, dict]]:
    """Find the tenant whose Twilio integration owns this `To` phone number.

    Returns (tenant_id, integration_config, decrypted_creds) or None.
    """
    target = _normalize_phone(to_number)
    if not target:
        return None

    # Pull all active twilio_sms configs across tenants. This is multi-tenant
    # by design — one webhook URL serves every tenant on the platform; the
    # selector is the dialed number.
    configs = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.integration_name == TWILIO_INTEGRATION_NAME,
            IntegrationConfig.enabled.is_(True),
        )
        .all()
    )
    for cfg in configs:
        creds = retrieve_credentials_for_skill(db, cfg.id, cfg.tenant_id)
        stored = _normalize_phone(creds.get("phone_number"))
        if stored and stored == target:
            return cfg.tenant_id, cfg, creds
    return None


def _pick_agent(db: Session, tenant_id: uuid.UUID) -> Optional[Agent]:
    """Prefer the Pet Health Concierge agent for SMS; fall back to any agent."""
    # Try the named agent first (case-insensitive). The Pet Health Concierge
    # persona explicitly markets itself as multi-channel including SMS, so it
    # owns the channel by default. Tenants without it (e.g. AgentProvision
    # itself) fall back to whatever native agent the tenant has.
    agent = (
        db.query(Agent)
        .filter(
            Agent.tenant_id == tenant_id,
            Agent.name.ilike("Pet Health Concierge"),
        )
        .first()
    )
    if agent:
        return agent

    # Fallback: any production-ish agent on the tenant.
    return (
        db.query(Agent)
        .filter(Agent.tenant_id == tenant_id)
        .order_by(Agent.created_at.asc() if hasattr(Agent, "created_at") else Agent.id.asc())
        .first()
    )


def _get_or_create_channel_account(
    db: Session,
    tenant_id: uuid.UUID,
    integration_config: IntegrationConfig,
    phone_number: str,
) -> ChannelAccount:
    """Mirror the pattern in whatsapp_service: one channel_account row per tenant SMS line."""
    account_id = phone_number or "default"
    acct = (
        db.query(ChannelAccount)
        .filter(
            ChannelAccount.tenant_id == tenant_id,
            ChannelAccount.channel_type == "sms",
            ChannelAccount.account_id == account_id,
        )
        .first()
    )
    if acct:
        return acct
    acct = ChannelAccount(
        tenant_id=tenant_id,
        channel_type="sms",
        account_id=account_id,
        enabled=True,
        status="connected",
        phone_number=phone_number,
        config={"integration_config_id": str(integration_config.id)},
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct


def _log_event(
    db: Session,
    tenant_id: uuid.UUID,
    channel_account_id: uuid.UUID,
    direction: str,
    remote_id: str,
    message_content: str,
    extra: dict | None = None,
    chat_session_id: uuid.UUID | None = None,
):
    try:
        evt = ChannelEvent(
            tenant_id=tenant_id,
            channel_account_id=channel_account_id,
            event_type=f"message_{direction}",
            direction=direction,
            remote_id=remote_id,
            message_content=message_content,
            chat_session_id=chat_session_id,
            extra_data=extra or {},
        )
        db.add(evt)
        db.commit()
    except Exception:  # pragma: no cover — audit log failure should never abort the request
        logger.exception("Failed to log channel_event")
        db.rollback()


# ---------------------------------------------------------------------------
# Twilio outbound
# ---------------------------------------------------------------------------

async def _send_twilio_sms(
    *, account_sid: str, auth_token: str, from_number: str, to_number: str, body: str,
) -> dict:
    """POST to Twilio's REST API to send an SMS. Returns Twilio JSON response."""
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    data = {"From": from_number, "To": to_number, "Body": body}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, data=data, auth=(account_sid, auth_token))
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_twilio_signature(
    *, signature: str | None, full_url: str, params: dict, auth_token: str,
) -> bool:
    """Verify Twilio's X-Twilio-Signature header.

    Uses the official `twilio` SDK if installed, otherwise falls back to a
    minimal HMAC-SHA1 implementation that matches the canonical algorithm
    documented at https://www.twilio.com/docs/usage/security#validating-requests
    """
    if not signature:
        return False

    # Prefer the official SDK to track Twilio's algorithm if it ever changes.
    try:
        from twilio.request_validator import RequestValidator  # type: ignore
    except ImportError:
        RequestValidator = None  # type: ignore

    if RequestValidator is not None:
        validator = RequestValidator(auth_token)
        return bool(validator.validate(full_url, params, signature))

    # Pure-Python fallback. Sort form params, concat key+value pairs, append
    # to the URL, HMAC-SHA1 with the auth token, base64.
    import base64
    import hashlib
    import hmac as _hmac

    sorted_pairs = "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
    raw = f"{full_url}{sorted_pairs}".encode("utf-8")
    digest = _hmac.new(auth_token.encode("utf-8"), raw, hashlib.sha1).digest()
    computed = base64.b64encode(digest).decode("utf-8")
    return _hmac.compare_digest(computed, signature)


def _resolve_public_url(request: Request) -> str:
    """Twilio signs the canonical PUBLIC URL — what they POSTed to.

    In Cloudflare-tunneled deployments the inside hostname is `api:8000` but
    Twilio signed against e.g. https://agentprovision.com/.... Trust
    `X-Forwarded-Proto` / `X-Forwarded-Host` when present (set by the tunnel
    + proxies), then fall back to the request URL.
    """
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    fwd_proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    path = request.url.path
    query = ("?" + request.url.query) if request.url.query else ""
    if fwd_host:
        return f"{fwd_proto}://{fwd_host}{path}{query}"
    return str(request.url)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/integrations/twilio/inbound")
async def twilio_inbound_sms(request: Request) -> Response:
    """Receive an inbound SMS from Twilio.

    Twilio always POSTs application/x-www-form-urlencoded. Returns an empty
    TwiML <Response/> so Twilio doesn't auto-reply on its side; the actual
    agent reply is sent asynchronously via the REST API.
    """
    form = await request.form()
    params = {k: v for k, v in form.items() if isinstance(v, str)}

    from_number = params.get("From", "")
    to_number = params.get("To", "")
    body = params.get("Body", "")
    message_sid = params.get("MessageSid", "")

    if not from_number or not to_number:
        raise HTTPException(status_code=400, detail="Missing From/To")

    db = SessionLocal()
    try:
        resolved = _resolve_tenant_for_to_number(db, to_number)
        if not resolved:
            logger.warning("Twilio inbound: no tenant matches To=%s", to_number)
            # Don't reveal whether the number is registered — return generic 404.
            raise HTTPException(status_code=404, detail="Unknown destination")

        tenant_id, cfg, creds = resolved
        auth_token = creds.get("auth_token") or ""
        account_sid = creds.get("account_sid") or ""
        clinic_number = creds.get("phone_number") or to_number

        # Signature verification — guard the endpoint
        if _signature_required():
            full_url = _resolve_public_url(request)
            signature = request.headers.get("x-twilio-signature")
            if not _verify_twilio_signature(
                signature=signature, full_url=full_url, params=params, auth_token=auth_token,
            ):
                logger.warning(
                    "Twilio inbound: invalid signature tenant=%s url=%s sig=%r",
                    tenant_id, full_url, signature,
                )
                raise HTTPException(status_code=403, detail="Invalid signature")

        # Audit inbound
        acct = _get_or_create_channel_account(db, tenant_id, cfg, clinic_number)

        # Resolve agent + chat session
        agent = _pick_agent(db, tenant_id)
        if not agent:
            logger.error("Twilio inbound: no agent for tenant %s", tenant_id)
            _log_event(
                db, tenant_id, acct.id, "inbound", from_number, body,
                extra={"message_sid": message_sid, "error": "no_agent"},
            )
            raise HTTPException(status_code=503, detail="No agent available")

        user = db.query(User).filter(User.tenant_id == tenant_id).first()
        if not user:
            logger.error("Twilio inbound: no user for tenant %s", tenant_id)
            raise HTTPException(status_code=503, detail="No user for tenant")

        session_key = f"twilio_sms:{from_number}"
        session = (
            db.query(ChatSession)
            .filter(
                ChatSession.tenant_id == tenant_id,
                ChatSession.source == "twilio_sms",
                ChatSession.external_id == session_key,
            )
            .first()
        )
        if not session:
            session = ChatSession(
                title=f"SMS: {from_number}",
                tenant_id=tenant_id,
                agent_id=agent.id,
                source="twilio_sms",
                external_id=session_key,
            )
            db.add(session)
            db.commit()
            db.refresh(session)
        elif not session.agent_id:
            session.agent_id = agent.id
            db.commit()
            db.refresh(session)

        _log_event(
            db, tenant_id, acct.id, "inbound", from_number, body,
            extra={"message_sid": message_sid, "agent_id": str(agent.id)},
            chat_session_id=session.id,
        )

        # Dispatch to chat service in a thread pool — the CLI orchestrator path
        # is sync and would otherwise block the FastAPI event loop.
        from app.services import chat as chat_service

        _t0 = time.perf_counter()

        def _run_chat() -> Optional[str]:
            try:
                _user_msg, assistant_msg = chat_service.post_user_message(
                    db,
                    session=session,
                    user_id=user.id,
                    content=body,
                    sender_phone=from_number,
                )
                return assistant_msg.content if assistant_msg else None
            except Exception:
                logger.exception("post_user_message failed for SMS tenant=%s", tenant_id)
                return None

        response_text = await asyncio.to_thread(_run_chat)
        elapsed_ms = (time.perf_counter() - _t0) * 1000
        logger.info(
            "Twilio inbound: tenant=%s session=%s replied in %.0fms (len=%d)",
            tenant_id, str(session.id)[:8], elapsed_ms, len(response_text or ""),
        )

        if response_text:
            try:
                twilio_resp = await _send_twilio_sms(
                    account_sid=account_sid,
                    auth_token=auth_token,
                    from_number=clinic_number,
                    to_number=from_number,
                    body=response_text[:1600],  # SMS hard cap = 1600 chars per Twilio
                )
                _log_event(
                    db, tenant_id, acct.id, "outbound", from_number, response_text,
                    extra={
                        "message_sid": twilio_resp.get("sid", ""),
                        "in_reply_to": message_sid,
                        "agent_id": str(agent.id),
                    },
                    chat_session_id=session.id,
                )
            except Exception:
                logger.exception("Twilio outbound send failed tenant=%s", tenant_id)

        # Empty TwiML — Twilio's webhook expects 200 + valid TwiML or empty body.
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response/>',
            media_type="application/xml",
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Outbound helper used by the MCP send_sms tool. Exposed via internal route so
# MCP can call it without re-implementing credential decryption.
# ---------------------------------------------------------------------------

@router.post("/integrations/twilio/internal/send")
async def twilio_send_internal(
    payload: dict,
    request: Request,
):
    """Internal-only outbound SMS for the MCP send_sms tool.

    Header `X-Internal-Key` must match settings.API_INTERNAL_KEY (the same
    gate every other /internal/* route uses). Body:
        {"tenant_id": "...", "to": "+1...", "body": "..."}
    """
    from app.core.config import settings

    expected = settings.API_INTERNAL_KEY
    provided = request.headers.get("x-internal-key")
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid internal key")

    tenant_id = payload.get("tenant_id") or ""
    to_number = payload.get("to") or ""
    body = payload.get("body") or ""
    if not tenant_id or not to_number or not body:
        raise HTTPException(status_code=400, detail="tenant_id, to, body required")

    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant_id")

    db = SessionLocal()
    try:
        cfg = (
            db.query(IntegrationConfig)
            .filter(
                IntegrationConfig.tenant_id == tid,
                IntegrationConfig.integration_name == TWILIO_INTEGRATION_NAME,
                IntegrationConfig.enabled.is_(True),
            )
            .first()
        )
        if not cfg:
            raise HTTPException(status_code=404, detail="twilio_sms not configured for tenant")
        creds = retrieve_credentials_for_skill(db, cfg.id, tid)
        account_sid = creds.get("account_sid") or ""
        auth_token = creds.get("auth_token") or ""
        from_number = creds.get("phone_number") or ""
        if not account_sid or not auth_token or not from_number:
            raise HTTPException(status_code=400, detail="twilio_sms credentials incomplete")

        try:
            twilio_resp = await _send_twilio_sms(
                account_sid=account_sid,
                auth_token=auth_token,
                from_number=from_number,
                to_number=to_number,
                body=body[:1600],
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Twilio rejected: {e.response.text}")

        # Audit out-of-band sends too.
        acct = _get_or_create_channel_account(db, tid, cfg, from_number)
        _log_event(
            db, tid, acct.id, "outbound", to_number, body,
            extra={"message_sid": twilio_resp.get("sid", ""), "source": "mcp_send_sms"},
        )

        return {
            "status": "sent",
            "message_sid": twilio_resp.get("sid", ""),
            "to": to_number,
            "from": from_number,
        }
    finally:
        db.close()


@router.get("/integrations/twilio/internal/threads")
async def twilio_list_threads_internal(
    request: Request,
    tenant_id: str,
    limit: int = 20,
):
    """Internal: list recent SMS chat sessions for a tenant."""
    from app.core.config import settings

    expected = settings.API_INTERNAL_KEY
    provided = request.headers.get("x-internal-key")
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid internal key")

    try:
        tid = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant_id")

    db = SessionLocal()
    try:
        sessions = (
            db.query(ChatSession)
            .filter(
                ChatSession.tenant_id == tid,
                ChatSession.source == "twilio_sms",
            )
            .order_by(ChatSession.created_at.desc())
            .limit(min(max(limit, 1), 100))
            .all()
        )
        return {
            "threads": [
                {
                    "id": str(s.id),
                    "title": s.title,
                    "remote_number": (s.external_id or "").replace("twilio_sms:", ""),
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "agent_id": str(s.agent_id) if s.agent_id else None,
                }
                for s in sessions
            ]
        }
    finally:
        db.close()


@router.get("/integrations/twilio/internal/thread/{session_id}")
async def twilio_read_thread_internal(
    request: Request,
    session_id: str,
    tenant_id: str,
    limit: int = 50,
):
    """Internal: read messages from a SMS chat session."""
    from app.core.config import settings
    from app.models.chat import ChatMessage

    expected = settings.API_INTERNAL_KEY
    provided = request.headers.get("x-internal-key")
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="Invalid internal key")

    try:
        tid = uuid.UUID(tenant_id)
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id")

    db = SessionLocal()
    try:
        session = (
            db.query(ChatSession)
            .filter(
                ChatSession.id == sid,
                ChatSession.tenant_id == tid,
                ChatSession.source == "twilio_sms",
            )
            .first()
        )
        if not session:
            raise HTTPException(status_code=404, detail="Thread not found")

        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.created_at.asc())
            .limit(min(max(limit, 1), 500))
            .all()
        )
        return {
            "thread": {
                "id": str(session.id),
                "title": session.title,
                "remote_number": (session.external_id or "").replace("twilio_sms:", ""),
            },
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
        }
    finally:
        db.close()
