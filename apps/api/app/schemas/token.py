from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Token(BaseModel):
    """Login / refresh response. `refresh_token` and `expires_in` are
    new in PR `feat(auth): long-lived CLI sessions via refresh tokens`.
    Optional so older clients (web UI today) parsing only `access_token`
    + `token_type` aren't broken by the additions.
    """

    access_token: str
    token_type: str
    refresh_token: str | None = None
    # Seconds until the access_token expires. Matches OAuth2 §5.1 so
    # `claude-code-sdk`, `httpx-auth`, etc. light up automatically.
    expires_in: int | None = None


class TokenData(BaseModel):
    email: str | None = None


class RefreshTokenRequest(BaseModel):
    """Body for POST /auth/token/refresh."""

    refresh_token: str
    # Optional device-label override. Today the CLI just propagates the
    # one captured at login; future clients (browser extensions, IDE
    # plugins) may pass a friendlier label per-rotation.
    device_label: str | None = None


class SessionInfo(BaseModel):
    """One row in GET /auth/sessions — a still-active refresh token."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    device_label: str | None = None
    user_agent: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime
