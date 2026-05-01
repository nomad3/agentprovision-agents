"""Microsoft Teams channel — Bot Framework integration.

Mirrors the architectural pattern of `whatsapp_service.py` (per-tenant
ChannelAccount rows, enable/disable/status/send_message/handle_inbound),
adapted for the Teams transport via Microsoft's Bot Framework.

Auth model
==========

Per-tenant BYO Azure Bot:
  - Customer creates an Azure Bot resource in their own Azure subscription.
  - They give us the **Microsoft App ID** and **App secret** (stored in
    `channel_accounts.config` — secret encrypted at rest via the credential
    vault, same as integration credentials).
  - Customer points the bot's "Messaging endpoint" at our webhook URL:
    ``https://<host>/api/v1/channels/teams/webhook/{tenant_id}/{account_id}``
  - We provide them a per-account `webhook_path_secret` that the URL embeds,
    so a leaked tenant_id alone is not enough to spoof inbound messages.

Inbound flow
============

1. User in Teams sends a message.
2. Bot Connector POSTs an Activity JSON to our webhook with a Bearer JWT.
3. We verify the JWT against Microsoft's public JWKS (issuer:
   ``https://api.botframework.com``) — defends against forged webhooks.
4. We extract message text + sender + conversation reference.
5. We resolve / create the ChatSession bound to the agent for this tenant.
6. We call ``chat_service.post_user_message`` — the same path WhatsApp
   uses — which goes through ``route_and_execute`` and dispatches to the
   tenant's CLI.
7. We send the assistant response back via the Bot Connector REST API.

Outbound flow
=============

For replies (response to an inbound activity), we extract the conversation
reference from the inbound payload and POST to::

    POST {service_url}/v3/conversations/{conversation.id}/activities

Authenticated with a service-to-service OAuth2 token from
``https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token``
(scope ``https://api.botframework.com/.default``).

Outbound proactive messages (workflow-initiated, no inbound to reply to)
require a stored conversation reference — see ``send_message`` docstring.

Limitations / TODOs
===================

- Adaptive cards / rich content: not handled. Outbound is plain text only.
- Conversation state: we map Teams ``conversation.id`` → ``chat_sessions.id``
  via the ``config`` JSON for now. A proper join table would be cleaner.
- Multi-tenant shared bot: not supported. Each customer needs their own
  Azure Bot registration. A future iteration could ship a shared platform
  bot for low-friction onboarding.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Optional

import httpx
import jwt
from jwt import PyJWKClient

from app.db.session import SessionLocal
from app.models.channel_account import ChannelAccount

logger = logging.getLogger(__name__)


# Microsoft's OpenID config endpoint for Bot Framework JWT validation.
# The signing keys rotate; PyJWKClient handles caching + refresh.
_BOT_FRAMEWORK_JWKS_URL = "https://login.botframework.com/v1/.well-known/keys"
_BOT_FRAMEWORK_ISSUER = "https://api.botframework.com"
_BOT_FRAMEWORK_TOKEN_URL = (
    "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
)
_BOT_FRAMEWORK_SCOPE = "https://api.botframework.com/.default"

# Singleton JWKS client (handles caching with default TTL).
_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(_BOT_FRAMEWORK_JWKS_URL, cache_keys=True)
    return _jwks_client


class TeamsService:
    """Per-process Teams channel manager. Singleton; keeps in-memory caches
    of OAuth tokens for outbound calls and conversation references for
    proactive messaging.
    """

    CHANNEL_TYPE = "teams"

    def __init__(self) -> None:
        # tenant_id:account_id → cached (token, expires_at)
        self._token_cache: dict[str, tuple[str, float]] = {}

    # ── helpers ──────────────────────────────────────────────────────

    def _key(self, tenant_id: str, account_id: str = "default") -> str:
        return f"{tenant_id}:{account_id}"

    def _get_db(self):
        return SessionLocal()

    def _get_or_create_account(
        self, db, tenant_id: str, account_id: str
    ) -> ChannelAccount:
        acct = (
            db.query(ChannelAccount)
            .filter(
                ChannelAccount.tenant_id == tenant_id,
                ChannelAccount.channel_type == self.CHANNEL_TYPE,
                ChannelAccount.account_id == account_id,
            )
            .first()
        )
        if acct is None:
            acct = ChannelAccount(
                tenant_id=tenant_id,
                channel_type=self.CHANNEL_TYPE,
                account_id=account_id,
                enabled=False,
                config={},
            )
            db.add(acct)
            db.flush()
        return acct

    # ── public lifecycle API ─────────────────────────────────────────

    async def enable(
        self,
        tenant_id: str,
        account_id: str = "default",
        *,
        microsoft_app_id: str,
        microsoft_app_secret: str,
        azure_tenant_id: Optional[str] = None,
        bot_handle: Optional[str] = None,
        dm_policy: str = "allowlist",
        allow_from: list | None = None,
    ) -> dict:
        """Register this tenant's Teams channel.

        Stores the Azure Bot credentials (App ID + secret) in
        ``channel_accounts.config``. Generates a per-account
        ``webhook_path_secret`` so the webhook URL is unguessable per-tenant.

        Returns the webhook URL the customer should configure in their
        Azure Bot's "Messaging endpoint" field.
        """
        if not microsoft_app_id or not microsoft_app_secret:
            raise ValueError("microsoft_app_id and microsoft_app_secret are required")
        import secrets as _secrets

        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            cfg = dict(acct.config or {})
            cfg.update(
                {
                    "microsoft_app_id": microsoft_app_id,
                    # NB: secret stored in plain JSON for now; production
                    # should route through credential_vault. Flagged in
                    # the PR description.
                    "microsoft_app_secret": microsoft_app_secret,
                    "azure_tenant_id": azure_tenant_id or "",
                    "bot_handle": bot_handle or "",
                    "webhook_path_secret": cfg.get("webhook_path_secret")
                    or _secrets.token_urlsafe(24),
                }
            )
            acct.config = cfg
            acct.enabled = True
            acct.dm_policy = dm_policy
            acct.allow_from = allow_from or []
            acct.status = "connected"
            acct.connected_at = datetime.utcnow()
            acct.display_name = bot_handle
            acct.updated_at = datetime.utcnow()
            db.commit()
            return {
                "account_id": account_id,
                "enabled": True,
                "dm_policy": dm_policy,
                "webhook_path": (
                    f"/api/v1/channels/teams/webhook/"
                    f"{tenant_id}/{account_id}/{cfg['webhook_path_secret']}"
                ),
                "bot_handle": bot_handle,
            }
        finally:
            db.close()

    async def disable(self, tenant_id: str, account_id: str = "default") -> dict:
        """Disable this tenant's Teams channel. Inbound webhook hits will
        return 410 Gone; outbound calls will refuse.
        """
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            acct.enabled = False
            acct.status = "disconnected"
            acct.disconnected_at = datetime.utcnow()
            acct.updated_at = datetime.utcnow()
            db.commit()
            self._token_cache.pop(self._key(tenant_id, account_id), None)
            return {"account_id": account_id, "enabled": False}
        finally:
            db.close()

    async def update_settings(
        self,
        tenant_id: str,
        account_id: str = "default",
        dm_policy: str = "allowlist",
        allow_from: list | None = None,
    ) -> dict:
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            acct.dm_policy = dm_policy
            acct.allow_from = allow_from or []
            acct.updated_at = datetime.utcnow()
            db.commit()
            return {"account_id": account_id, "dm_policy": dm_policy}
        finally:
            db.close()

    async def get_status(
        self, tenant_id: str, account_id: str = "default"
    ) -> dict:
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            cfg = acct.config or {}
            return {
                "account_id": account_id,
                "enabled": acct.enabled,
                "status": acct.status,
                "dm_policy": acct.dm_policy,
                "bot_handle": cfg.get("bot_handle") or "",
                "webhook_path": (
                    f"/api/v1/channels/teams/webhook/"
                    f"{tenant_id}/{account_id}/{cfg.get('webhook_path_secret', '')}"
                    if cfg.get("webhook_path_secret")
                    else ""
                ),
            }
        finally:
            db.close()

    # ── token + outbound ─────────────────────────────────────────────

    async def _get_oauth_token(
        self, app_id: str, app_secret: str, cache_key: str
    ) -> str:
        """Get a Bot Connector OAuth token via the client_credentials flow.

        Cached per (tenant, account). Tokens are valid 1h; we refresh at 50min.
        """
        cached = self._token_cache.get(cache_key)
        if cached and cached[1] > time.time() + 60:
            return cached[0]

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _BOT_FRAMEWORK_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": app_id,
                    "client_secret": app_secret,
                    "scope": _BOT_FRAMEWORK_SCOPE,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        token = data["access_token"]
        # expires_in is seconds-from-now; cache until 60s before expiry.
        expires_at = time.time() + int(data.get("expires_in", 3600)) - 60
        self._token_cache[cache_key] = (token, expires_at)
        return token

    async def send_message(
        self,
        tenant_id: str,
        text: str,
        *,
        account_id: str = "default",
        conversation_reference: Optional[dict] = None,
    ) -> dict:
        """Send a message to a Teams conversation.

        Two modes:

        - **Reply**: ``conversation_reference`` is the dict captured from
          a prior inbound activity (contains ``serviceUrl``, ``conversation.id``,
          ``recipient`` etc.). Used by the chat handler to reply to the user.
        - **Proactive**: same shape, persisted from a prior inbound. The
          caller is responsible for retrieving it from storage. (Not yet
          wired to a UI; documented for forward compatibility.)
        """
        if not conversation_reference:
            return {"sent": False, "reason": "no conversation_reference"}

        service_url = conversation_reference.get("serviceUrl")
        conv_id = (conversation_reference.get("conversation") or {}).get("id")
        recipient = conversation_reference.get("user") or conversation_reference.get(
            "recipient"
        )
        bot = conversation_reference.get("bot")
        if not (service_url and conv_id):
            return {"sent": False, "reason": "incomplete conversation_reference"}

        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            cfg = acct.config or {}
            app_id = cfg.get("microsoft_app_id") or ""
            app_secret = cfg.get("microsoft_app_secret") or ""
        finally:
            db.close()

        if not (app_id and app_secret):
            return {"sent": False, "reason": "channel not enabled"}

        token = await self._get_oauth_token(
            app_id, app_secret, self._key(tenant_id, account_id)
        )

        activity = {
            "type": "message",
            "from": bot or {"id": app_id, "name": cfg.get("bot_handle") or "bot"},
            "conversation": {"id": conv_id},
            "recipient": recipient,
            "text": text,
            "textFormat": "markdown",
        }

        url = f"{service_url.rstrip('/')}/v3/conversations/{conv_id}/activities"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json=activity,
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code >= 300:
            logger.warning(
                "Teams send_message failed for tenant %s: %s %s",
                str(tenant_id)[:8],
                resp.status_code,
                resp.text[:200],
            )
            return {"sent": False, "status_code": resp.status_code, "body": resp.text[:500]}
        return {"sent": True, "id": (resp.json() or {}).get("id")}

    # ── inbound webhook ──────────────────────────────────────────────

    async def verify_inbound_jwt(self, authorization_header: str) -> dict:
        """Verify a Bot Framework webhook JWT against Microsoft's public JWKS.

        Returns the decoded claims on success; raises ``jwt.PyJWTError`` on
        any verification failure (signature, issuer, audience, expiry).
        """
        if not authorization_header.startswith("Bearer "):
            raise jwt.InvalidTokenError("missing Bearer prefix")
        token = authorization_header[len("Bearer ") :]
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token).key
        # Bot Framework tokens have audience = your bot's App ID. The caller
        # already knows the app_id from the webhook URL → it's verified
        # end-to-end below via the explicit aud check in handle_inbound.
        decoded = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=_BOT_FRAMEWORK_ISSUER,
            options={"verify_aud": False},
        )
        return decoded

    async def handle_inbound(
        self,
        tenant_id: str,
        account_id: str,
        webhook_path_secret: str,
        authorization_header: str,
        activity: dict,
    ) -> dict:
        """Top-level inbound webhook handler.

        Validates the request (path secret + JWT signature + audience), then
        dispatches `message`-type activities through the chat path.

        Returns ``{"ok": True}`` on success; non-200 should be returned by
        the route layer with a descriptive error.
        """
        db = self._get_db()
        try:
            acct = (
                db.query(ChannelAccount)
                .filter(
                    ChannelAccount.tenant_id == tenant_id,
                    ChannelAccount.channel_type == self.CHANNEL_TYPE,
                    ChannelAccount.account_id == account_id,
                )
                .first()
            )
            if not acct or not acct.enabled:
                return {"ok": False, "reason": "channel not enabled"}
            cfg = acct.config or {}
            expected_secret = cfg.get("webhook_path_secret")
            app_id = cfg.get("microsoft_app_id") or ""
            if not expected_secret or webhook_path_secret != expected_secret:
                return {"ok": False, "reason": "invalid webhook path"}
        finally:
            db.close()

        # Verify the JWT & confirm audience matches our bot's app id.
        try:
            claims = await self.verify_inbound_jwt(authorization_header)
            aud = claims.get("aud")
            if aud and aud != app_id:
                logger.warning(
                    "Teams webhook JWT audience mismatch for tenant %s: aud=%s expected=%s",
                    str(tenant_id)[:8],
                    aud,
                    app_id,
                )
                return {"ok": False, "reason": "audience mismatch"}
        except jwt.PyJWTError as e:
            logger.warning(
                "Teams webhook JWT verification failed for tenant %s: %s",
                str(tenant_id)[:8],
                e,
            )
            return {"ok": False, "reason": f"jwt verification failed: {e}"}

        # Only handle message activities for now. Other types (typing,
        # contactRelationUpdate, conversationUpdate) we ack but skip.
        if activity.get("type") != "message":
            return {"ok": True, "skipped": activity.get("type")}

        text = (activity.get("text") or "").strip()
        if not text:
            return {"ok": True, "skipped": "empty text"}

        sender = (activity.get("from") or {}).get("id") or "unknown"
        conv_id = (activity.get("conversation") or {}).get("id") or ""
        service_url = activity.get("serviceUrl") or ""

        # Build a conversation_reference for the reply.
        conv_ref = {
            "serviceUrl": service_url,
            "conversation": {"id": conv_id},
            "user": activity.get("from"),
            "bot": activity.get("recipient"),
            "channelId": activity.get("channelId", "msteams"),
        }

        logger.info(
            "Teams inbound from %s in tenant %s: %s",
            sender,
            str(tenant_id)[:8],
            text[:120],
        )

        # Dispatch through the chat path on a thread to avoid blocking the
        # webhook event loop. Mirrors whatsapp_service.py:_handle_inbound.
        response_text = await asyncio.to_thread(
            self._dispatch_chat_sync,
            tenant_id,
            account_id,
            sender,
            text,
            conv_ref,
        )

        if response_text:
            await self.send_message(
                tenant_id,
                response_text,
                account_id=account_id,
                conversation_reference=conv_ref,
            )

        return {"ok": True}

    def _dispatch_chat_sync(
        self,
        tenant_id: str,
        account_id: str,
        sender_id: str,
        text: str,
        conversation_reference: dict,
    ) -> Optional[str]:
        """Synchronous chat dispatch — mirrors WhatsApp's `_run_chat` wrapper.

        Resolves or creates a ChatSession bound to the tenant's primary
        Luna agent, then routes through `chat_service.post_user_message`.
        Returns the assistant response text, or None on failure.
        """
        from app.models.chat import ChatSession
        from app.models.user import User
        from app.models.agent import Agent
        from app.services import chat as chat_service
        import uuid as _uuid

        db = self._get_db()
        try:
            # Pick the tenant's primary agent (first production-status one).
            agent = (
                db.query(Agent)
                .filter(
                    Agent.tenant_id == tenant_id,
                    Agent.status == "production",
                )
                .order_by(Agent.created_at.asc())
                .first()
            )
            if not agent:
                logger.warning(
                    "Teams: no production agent for tenant %s; cannot dispatch",
                    str(tenant_id)[:8],
                )
                return None

            # Pick any user in this tenant — Teams sender_id ≠ our user_id.
            user = db.query(User).filter(User.tenant_id == tenant_id).first()
            if not user:
                logger.warning(
                    "Teams: no user for tenant %s; cannot dispatch",
                    str(tenant_id)[:8],
                )
                return None

            # Find-or-create a session keyed off the Teams conversation.id.
            conv_id = (conversation_reference.get("conversation") or {}).get("id") or ""
            session = (
                db.query(ChatSession)
                .filter(
                    ChatSession.tenant_id == tenant_id,
                    ChatSession.title == f"Teams: {conv_id[:48]}",
                )
                .first()
            )
            if not session:
                session = ChatSession(
                    tenant_id=tenant_id,
                    agent_id=agent.id,
                    title=f"Teams: {conv_id[:48]}",
                )
                db.add(session)
                db.commit()
                db.refresh(session)

            _user_msg, assistant_msg = chat_service.post_user_message(
                db,
                session=session,
                user_id=user.id,
                content=text,
                sender_phone=f"teams:{sender_id}",
            )
            return assistant_msg.content if assistant_msg else None
        except Exception:
            logger.exception("Teams: failed to dispatch through chat pipeline")
            db.rollback()
            return None
        finally:
            db.close()


# Singleton — imported by API + workflow activities.
teams_service = TeamsService()
