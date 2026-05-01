"""Microsoft Teams channel — Microsoft Graph integration.

Reuses the existing `microsoft` OAuth provider that Outlook already uses
(``apps/api/app/api/v1/oauth.py``). Same app registration, same token
endpoint, same credential-vault storage. Adds Teams-specific scopes
(``Chat.ReadWrite``, ``ChannelMessage.Send``, ``Team.ReadBasic.All``) so
the same access token can list Teams chats, send messages, and read
channel messages.

Architecture
============

**Auth**: delegated OAuth — the user authorizes the platform's
microsoft app once, the resulting access_token (with refresh) lives in
``integration_credentials`` keyed by the ``outlook``/``teams``
integration_config rows. ``email.py`` already uses this token against
``https://graph.microsoft.com/v1.0/me/messages``; we use it against
``/me/chats`` and ``/teams``.

**Inbound — polling, not webhooks** (V1):
  - A ``TeamsMonitorWorkflow`` (analogous to ``InboxMonitorWorkflow``)
    polls each enabled tenant every N minutes for new chat messages
    received since the last poll.
  - Each new message is dispatched through ``chat_service.post_user_message``
    — the same path WhatsApp/Teams-Bot uses — and the assistant response
    is sent back via Graph.
  - Polling avoids the complexity of Graph change-notification
    subscriptions (which expire every 60 minutes for chat resources and
    require renewal). A subscription-based path can be added later if
    sub-minute latency matters.

**Outbound**: ``POST /me/chats/{chatId}/messages`` (1:1 / group chats) or
``POST /teams/{teamId}/channels/{channelId}/messages`` (channel posts).

Limitations
-----------

1. **Acts as the user**, not as a separate "Luna" identity. The token is
   delegated, so messages Luna sends appear in the user's outgoing-messages
   pane and reply-from address is the user's own UPN. For a true bot
   identity (separate participant in chats), use Bot Framework instead.
2. **Polling latency** — N-minute resolution.
3. **Channel @-mentions** — tracking which channel posts mention the user
   is the responsibility of the monitor workflow (not implemented in V1).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.db.session import SessionLocal
from app.models.channel_account import ChannelAccount
from app.models.integration_config import IntegrationConfig
from app.services.orchestration.credential_vault import retrieve_credentials_for_skill

logger = logging.getLogger(__name__)


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TEAMS_INTEGRATION_NAME = "teams"


class TeamsService:
    """Per-process Teams channel manager. Singleton; no in-memory state
    (tokens come from the credential vault on each call so that token
    rotations propagate instantly across worker processes).
    """

    CHANNEL_TYPE = "teams"

    # ── helpers ──────────────────────────────────────────────────────

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

    def _get_access_token(self, tenant_id: str) -> Optional[str]:
        """Pull the microsoft Graph access_token from integration_credentials.

        Reuses the same `outlook`/`teams` integration_config row that the
        Outlook flow already populates. Returns None if no token configured.
        """
        db = self._get_db()
        try:
            cfg = (
                db.query(IntegrationConfig)
                .filter(
                    IntegrationConfig.tenant_id == tenant_id,
                    IntegrationConfig.integration_name.in_(
                        [TEAMS_INTEGRATION_NAME, "outlook"]
                    ),
                    IntegrationConfig.enabled.is_(True),
                )
                .order_by(
                    # Prefer the dedicated `teams` integration_config if it
                    # exists; fall back to `outlook`'s token (same provider).
                    IntegrationConfig.integration_name.desc()
                )
                .first()
            )
            if not cfg:
                return None
            creds = retrieve_credentials_for_skill(
                db,
                integration_config_id=cfg.id,
                tenant_id=cfg.tenant_id,
            )
            return creds.get("access_token") or creds.get("oauth_token")
        finally:
            db.close()

    # ── public lifecycle API ─────────────────────────────────────────

    async def enable(
        self,
        tenant_id: str,
        account_id: str = "default",
        *,
        dm_policy: str = "allowlist",
        allow_from: list | None = None,
    ) -> dict:
        """Enable the Teams channel for this tenant.

        Pre-condition: the tenant has already authorized the `microsoft`
        OAuth provider (typically via the Outlook integration card). This
        endpoint just flips the channel_account to enabled — the actual
        Graph token is read from integration_credentials at call time.
        """
        if not self._get_access_token(tenant_id):
            return {
                "enabled": False,
                "reason": (
                    "no microsoft Graph token. Connect Outlook (or another "
                    "microsoft provider integration) first; the Teams scopes "
                    "are added to the same OAuth flow."
                ),
            }
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            acct.enabled = True
            acct.dm_policy = dm_policy
            acct.allow_from = allow_from or []
            acct.status = "connected"
            acct.connected_at = datetime.utcnow()
            acct.updated_at = datetime.utcnow()
            db.commit()
            return {"account_id": account_id, "enabled": True, "dm_policy": dm_policy}
        finally:
            db.close()

    async def disable(self, tenant_id: str, account_id: str = "default") -> dict:
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            acct.enabled = False
            acct.status = "disconnected"
            acct.disconnected_at = datetime.utcnow()
            acct.updated_at = datetime.utcnow()
            db.commit()
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
            has_token = bool(self._get_access_token(tenant_id))
            return {
                "account_id": account_id,
                "enabled": acct.enabled,
                "status": acct.status,
                "dm_policy": acct.dm_policy,
                "graph_token_present": has_token,
                "last_polled_at": (acct.config or {}).get("last_polled_at"),
            }
        finally:
            db.close()

    # ── Graph API wrappers ───────────────────────────────────────────

    async def list_chats(self, tenant_id: str) -> list[dict]:
        """List the user's recent Teams chats (1:1 + group)."""
        token = self._get_access_token(tenant_id)
        if not token:
            return []
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/chats",
                headers={"Authorization": f"Bearer {token}"},
                params={"$top": 50},
            )
        if resp.status_code >= 300:
            logger.warning(
                "Teams list_chats failed for tenant %s: %s %s",
                str(tenant_id)[:8], resp.status_code, resp.text[:200],
            )
            return []
        return (resp.json() or {}).get("value") or []

    async def fetch_recent_messages(
        self,
        tenant_id: str,
        *,
        since_iso: Optional[str] = None,
        max_results: int = 50,
    ) -> list[dict]:
        """Fetch chat messages received since `since_iso` across all the
        user's chats. Uses Graph's ``/me/chats/getAllMessages`` aggregator
        endpoint (avoids fanning out per-chat).

        Returns the raw Graph chatMessage objects. Caller filters for
        messages that aren't from the user themselves.
        """
        token = self._get_access_token(tenant_id)
        if not token:
            return []
        params: dict[str, Any] = {"$top": max_results}
        if since_iso:
            # Graph filter on createdDateTime for getAllMessages
            params["$filter"] = f"createdDateTime gt {since_iso}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/chats/getAllMessages",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
        if resp.status_code >= 300:
            logger.warning(
                "Teams fetch_recent_messages failed for tenant %s: %s %s",
                str(tenant_id)[:8], resp.status_code, resp.text[:200],
            )
            return []
        return (resp.json() or {}).get("value") or []

    async def send_chat_message(
        self,
        tenant_id: str,
        chat_id: str,
        text: str,
    ) -> dict:
        """POST a message to a 1:1 or group chat by chat_id."""
        token = self._get_access_token(tenant_id)
        if not token:
            return {"sent": False, "reason": "no graph token"}
        body = {"body": {"contentType": "text", "content": text}}
        url = f"{GRAPH_BASE}/me/chats/{chat_id}/messages"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
        if resp.status_code >= 300:
            logger.warning(
                "Teams send_chat_message failed for tenant %s chat %s: %s %s",
                str(tenant_id)[:8], chat_id[:12], resp.status_code, resp.text[:200],
            )
            return {"sent": False, "status_code": resp.status_code, "body": resp.text[:500]}
        return {"sent": True, "id": (resp.json() or {}).get("id")}

    async def send_channel_message(
        self,
        tenant_id: str,
        team_id: str,
        channel_id: str,
        text: str,
    ) -> dict:
        """POST a message to a Team channel."""
        token = self._get_access_token(tenant_id)
        if not token:
            return {"sent": False, "reason": "no graph token"}
        body = {"body": {"contentType": "text", "content": text}}
        url = f"{GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
        if resp.status_code >= 300:
            logger.warning(
                "Teams send_channel_message failed for tenant %s team %s: %s %s",
                str(tenant_id)[:8], team_id[:12], resp.status_code, resp.text[:200],
            )
            return {"sent": False, "status_code": resp.status_code, "body": resp.text[:500]}
        return {"sent": True, "id": (resp.json() or {}).get("id")}

    # ── poll-driven monitor entry point ──────────────────────────────

    async def monitor_tick(
        self, tenant_id: str, account_id: str = "default"
    ) -> dict:
        """One iteration of the Teams Monitor.

        - Reads the last-polled cursor from the channel_account.
        - Fetches new chat messages via Graph.
        - For each new message NOT from the user themselves, dispatches
          through the chat path (`chat_service.post_user_message`).
        - Sends Luna's response back via `send_chat_message`.
        - Updates the cursor.

        Returns counts of fetched / triaged / replied for observability.
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
            cfg = dict(acct.config or {})
            since = cfg.get("last_polled_at")
        finally:
            db.close()

        # Default cursor: fetch the last 5 minutes if no prior poll.
        if not since:
            from datetime import timedelta as _td
            since = (datetime.now(timezone.utc) - _td(minutes=5)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        messages = await self.fetch_recent_messages(tenant_id, since_iso=since)
        # Get the user's UPN/id so we can skip messages from themselves.
        token = self._get_access_token(tenant_id)
        my_id: Optional[str] = None
        if token:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    me = await client.get(
                        f"{GRAPH_BASE}/me?$select=id",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if me.status_code < 300:
                        my_id = (me.json() or {}).get("id")
            except Exception:
                pass

        fetched = len(messages)
        replied = 0
        for msg in messages:
            sender = ((msg.get("from") or {}).get("user") or {}).get("id")
            if my_id and sender == my_id:
                continue  # skip our own messages
            chat_id = msg.get("chatId")
            text = ((msg.get("body") or {}).get("content") or "").strip()
            if not (chat_id and text):
                continue
            response = await self._dispatch_chat_async(
                tenant_id, account_id, sender or "unknown", text, chat_id
            )
            if response:
                send_result = await self.send_chat_message(tenant_id, chat_id, response)
                if send_result.get("sent"):
                    replied += 1

        # Advance cursor to "now".
        new_cursor = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            cfg = dict(acct.config or {})
            cfg["last_polled_at"] = new_cursor
            acct.config = cfg
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(acct, "config")
            db.commit()
        finally:
            db.close()

        return {"ok": True, "fetched": fetched, "replied": replied, "cursor": new_cursor}

    async def _dispatch_chat_async(
        self,
        tenant_id: str,
        account_id: str,
        sender_id: str,
        text: str,
        chat_id: str,
    ) -> Optional[str]:
        """Dispatch through `chat_service.post_user_message` on a worker
        thread. Mirrors WhatsApp's `_run_chat`.
        """
        import asyncio

        def _do() -> Optional[str]:
            from app.models.chat import ChatSession
            from app.models.user import User
            from app.models.agent import Agent
            from app.services import chat as chat_service

            db = self._get_db()
            try:
                agent = (
                    db.query(Agent)
                    .filter(
                        Agent.tenant_id == tenant_id,
                        Agent.status == "production",
                    )
                    .order_by(Agent.created_at.asc())
                    .first()
                )
                user = db.query(User).filter(User.tenant_id == tenant_id).first()
                if not agent or not user:
                    return None
                session_title = f"Teams: {chat_id[:48]}"
                session = (
                    db.query(ChatSession)
                    .filter(
                        ChatSession.tenant_id == tenant_id,
                        ChatSession.title == session_title,
                    )
                    .first()
                )
                if not session:
                    session = ChatSession(
                        tenant_id=tenant_id,
                        agent_id=agent.id,
                        title=session_title,
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
                logger.exception("Teams: chat dispatch failed")
                db.rollback()
                return None
            finally:
                db.close()

        return await asyncio.to_thread(_do)


# Singleton — imported by API + workflow activities.
teams_service = TeamsService()
