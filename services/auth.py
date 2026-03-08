"""JWT authentication service.

Shares SECRET_KEY with FastAPI for consistent token validation.
"""
from typing import Optional
from datetime import datetime
from jose import JWTError, jwt
from pydantic import BaseModel

from config.settings import settings


class TokenData(BaseModel):
    """Decoded JWT token data."""
    sub: str  # User email
    tenant_id: Optional[str] = None
    user_id: Optional[str] = None
    exp: Optional[datetime] = None


def decode_token(token: str) -> Optional[TokenData]:
    """Decode and validate JWT token.

    Args:
        token: JWT token string (without 'Bearer ' prefix)

    Returns:
        TokenData if valid, None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )

        return TokenData(
            sub=payload.get("sub", ""),
            tenant_id=payload.get("tenant_id"),
            user_id=payload.get("user_id"),
            exp=datetime.fromtimestamp(payload.get("exp", 0)) if payload.get("exp") else None,
        )
    except JWTError:
        return None


def extract_token_from_header(authorization: str) -> Optional[str]:
    """Extract token from Authorization header.

    Args:
        authorization: Full Authorization header value

    Returns:
        Token string if valid Bearer token, None otherwise
    """
    if not authorization:
        return None

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1]


def validate_request(authorization: str) -> Optional[TokenData]:
    """Validate request authorization.

    Args:
        authorization: Authorization header value

    Returns:
        TokenData if valid, None if invalid
    """
    token = extract_token_from_header(authorization)
    if not token:
        return None

    return decode_token(token)


def get_tenant_id_from_token(authorization: str) -> Optional[str]:
    """Extract tenant_id from authorization header.

    Args:
        authorization: Authorization header value

    Returns:
        Tenant ID if valid, None otherwise
    """
    token_data = validate_request(authorization)
    if not token_data:
        return None

    return token_data.tenant_id
