"""Refresh-token issuance, rotation, and revocation.

The service layer for `apps/api/app/api/v1/auth.py`. Keeps the route
handlers thin and gives the test suite a single seam to mock.

Rotation semantics: a fresh refresh token is minted on every successful
`/auth/token/refresh` exchange. The presented token is marked
`revoked_at = now()` + `revoked_reason = 'rotated'`. If the **same** token
is presented twice (clear sign of a leak / replay), we walk the chain
backwards via `parent_id` and revoke every still-live link. This is the
"refresh-token rotation with reuse detection" pattern recommended in
RFC 6749bis and used by Auth0, Okta, Cognito, et al.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.refresh_token import RefreshToken
from app.models.user import User


def _hash_secret(secret: str) -> str:
    """sha256 in lowercase hex. The DB column is CHAR(64); collision
    space is effectively zero for ≤2^60 tokens, well above any plausible
    user count over the product lifetime."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _new_secret() -> str:
    """256 bits of entropy, URL-safe. Matches Auth0 / GitHub PAT length.
    `secrets.token_urlsafe(32)` returns 43 chars."""
    return secrets.token_urlsafe(32)


def issue_refresh_token(
    db: Session,
    *,
    user: User,
    device_label: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
    parent: Optional[RefreshToken] = None,
) -> Tuple[str, RefreshToken]:
    """Mint a fresh refresh token. Returns `(plaintext_secret, row)`.

    The plaintext is the only time the secret is materialized in
    process memory — it flows back to the caller (CLI / web) and is
    NEVER persisted. We persist `sha256(plaintext)` only.

    `parent` is set when this token is a rotation of an existing one,
    so the chain is walkable for reuse detection.
    """
    secret = _new_secret()
    row = RefreshToken(
        user_id=user.id,
        token_hash=_hash_secret(secret),
        parent_id=parent.id if parent is not None else None,
        device_label=device_label,
        user_agent=user_agent,
        ip_inet=ip,
        expires_at=datetime.utcnow()
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(row)
    db.flush()  # populate row.id before commit so the caller can log it
    return secret, row


def find_active(db: Session, *, secret: str) -> Optional[RefreshToken]:
    """Look up a refresh token by its plaintext secret. Returns None if
    not found, revoked, or expired. Callers MUST check `is_active()`
    themselves if they want to distinguish 'expired vs revoked vs missing'.
    """
    hashed = _hash_secret(secret)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == hashed).first()
    if row is None:
        return None
    if not row.is_active():
        return None
    return row


def revoke_chain_from(
    db: Session,
    *,
    leaf: RefreshToken,
    reason: str,
) -> int:
    """Walk `leaf` → parent → parent → … and revoke every still-live
    link. Used on reuse detection: if a presented token was already
    rotated (revoked_reason='rotated' on the row we found by hash),
    we don't know which link in the chain leaked, so we kill the whole
    family. Returns the number of rows revoked."""
    now = datetime.utcnow()
    count = 0
    node: Optional[RefreshToken] = leaf
    while node is not None:
        if node.revoked_at is None:
            node.revoked_at = now
            node.revoked_reason = reason
            count += 1
        node = node.parent
    # Also revoke any not-yet-revoked descendants of leaf (children
    # already rotated past it). The relationship backref `children`
    # populated on the model gives us O(branching factor) per node.
    stack = list(leaf.children)
    while stack:
        node = stack.pop()
        if node.revoked_at is None:
            node.revoked_at = now
            node.revoked_reason = reason
            count += 1
        stack.extend(node.children)
    db.flush()
    return count


def rotate(
    db: Session,
    *,
    presented: RefreshToken,
    user_agent: Optional[str] = None,
    ip: Optional[str] = None,
) -> Tuple[str, RefreshToken]:
    """Exchange `presented` for a fresh refresh token.

    The presented row MUST be active when this is called (callers
    `find_active()` first). On success: returns `(new_plaintext, new_row)`,
    marks `presented.revoked_at = now()` + `revoked_reason = 'rotated'`,
    and bumps `presented.last_used_at`.

    Device label, user_agent, ip carry forward from the previous link
    (overridden by the caller's `user_agent` / `ip` if provided).
    """
    new_secret, new_row = issue_refresh_token(
        db,
        user=presented.user,
        device_label=presented.device_label,
        user_agent=user_agent or presented.user_agent,
        ip=ip or (str(presented.ip_inet) if presented.ip_inet else None),
        parent=presented,
    )
    now = datetime.utcnow()
    presented.revoked_at = now
    presented.revoked_reason = "rotated"
    presented.last_used_at = now
    db.flush()
    return new_secret, new_row


def revoke_one(
    db: Session,
    *,
    row: RefreshToken,
    reason: str = "user_revoked",
) -> None:
    """Revoke a single refresh token (e.g. `alpha sessions revoke <id>`
    or web logout). Idempotent — no-op if already revoked."""
    if row.revoked_at is not None:
        return
    row.revoked_at = datetime.utcnow()
    row.revoked_reason = reason
    db.flush()
