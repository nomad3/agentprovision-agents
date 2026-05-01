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

# Cap how many message IDs we keep on the channel_account.config for
# dedup. Graph rarely returns more than a handful per tick; 500 is plenty
# of headroom and keeps the JSONB row small.
_PROCESSED_IDS_CAP = 500

# Hard cap on chats and messages per Graph poll. Pagination follows
# `@odata.nextLink` until the cap is hit. Tenants with massive Teams
# footprints would otherwise either hit our timeouts or silently truncate.
_LIST_CHATS_CAP = 500
_FETCH_MESSAGES_CAP = 200


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
        """Pull a fresh microsoft Graph access_token, refreshing if stale.

        Microsoft delegated-auth access tokens are 1-hour-lived. Reading the
        stored token directly (which was the V1 behavior) means every call
        breaks 60 minutes after authorization. This helper:

          1. Loads the integration_config (preferring a dedicated `teams`
             row, falling back to `outlook` on the same microsoft provider).
          2. Pulls the stored access_token + refresh_token from the vault.
          3. If a refresh_token is available, calls the same Microsoft token
             endpoint that ``oauth.py`` uses, persists the rotated tokens
             back to the vault, and returns the fresh access_token.
          4. Falls back to the stored access_token if refresh fails (the
             caller will surface a 401 from Graph and the user can re-auth).

        Returns None if no microsoft credential exists for this tenant.
        """
        # Lazy import to avoid pulling oauth.py (and its circular FastAPI
        # router setup) during module load.
        from app.api.v1.oauth import _refresh_access_token, _update_stored_tokens

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
            stored_token = creds.get("access_token") or creds.get("oauth_token")
            refresh_token = creds.get("refresh_token")

            # If we don't have a refresh_token on this config, look at the
            # sibling configs for the same microsoft account (oauth.py's
            # internal token endpoint does this too — Microsoft returns one
            # refresh_token per OAuth flow even when the user enables both
            # outlook and teams in the same consent).
            if not refresh_token and cfg.account_email:
                siblings = (
                    db.query(IntegrationConfig)
                    .filter(
                        IntegrationConfig.tenant_id == tenant_id,
                        IntegrationConfig.account_email == cfg.account_email,
                        IntegrationConfig.enabled.is_(True),
                        IntegrationConfig.id != cfg.id,
                    )
                    .all()
                )
                for sib in siblings:
                    sib_creds = retrieve_credentials_for_skill(
                        db, integration_config_id=sib.id, tenant_id=cfg.tenant_id,
                    )
                    if sib_creds.get("refresh_token"):
                        refresh_token = sib_creds["refresh_token"]
                        break

            if not refresh_token:
                return stored_token

            try:
                refreshed = _refresh_access_token(
                    "microsoft", refresh_token, integration_name=cfg.integration_name,
                )
            except Exception as e:
                logger.warning(
                    "Teams: token refresh raised for tenant=%s: %s",
                    str(tenant_id)[:8], e,
                )
                refreshed = None

            if not refreshed or not refreshed.get("access_token"):
                # Stored token may still be valid for some of its window;
                # let the caller try and surface the 401 if it expired.
                return stored_token

            try:
                _update_stored_tokens(
                    db,
                    cfg.id,
                    cfg.tenant_id,
                    refreshed["access_token"],
                    refreshed.get("refresh_token"),
                )
                db.commit()
            except Exception:
                logger.warning(
                    "Teams: failed to persist rotated token for tenant=%s",
                    str(tenant_id)[:8],
                )
                db.rollback()
            return refreshed["access_token"]
        finally:
            db.close()

    @staticmethod
    def _is_sender_allowed(acct: ChannelAccount, sender_id: str, sender_upn: str = "") -> bool:
        """Return True if the inbound sender passes the channel's DM policy.

        Mirrors the WhatsApp service's allowlist gate (which the V1 of this
        service forgot to wire up). ``allow_from`` may contain user IDs (the
        ``id`` from Graph's ``from.user`` block), UPNs (``user@domain``), or
        ``"*"`` for open. Match is case-insensitive on UPNs.
        """
        policy = (acct.dm_policy or "allowlist").lower()
        if policy != "allowlist":
            return True
        allowed = acct.allow_from or []
        if "*" in allowed:
            return True
        sender_id_l = (sender_id or "").lower()
        sender_upn_l = (sender_upn or "").lower()
        for entry in allowed:
            e = (entry or "").lower()
            if not e:
                continue
            if e == sender_id_l or e == sender_upn_l:
                return True
        return False

    async def _probe_teams_scope(self, token: str) -> tuple[bool, str]:
        """Verify the token has Teams scopes by probing /me/chats?$top=1.

        Outlook-only tokens (Mail.* scopes) will get 403 from Graph for any
        Chat.* endpoint. Surface that as a useful enable() error rather
        than letting every later call fail silently.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{GRAPH_BASE}/me/chats",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$top": 1},
                )
            if resp.status_code < 300:
                return True, ""
            if resp.status_code in (401, 403):
                return False, (
                    "microsoft token lacks Teams scopes. Re-authorize the "
                    "microsoft provider — the integration card now requests "
                    "Chat.ReadWrite, ChannelMessage.Send, Team.ReadBasic.All."
                )
            return False, f"Graph probe returned {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            return False, f"Graph probe failed: {e}"

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
        token = self._get_access_token(tenant_id)
        if not token:
            return {
                "enabled": False,
                "reason": (
                    "no microsoft Graph token. Connect Outlook (or another "
                    "microsoft provider integration) first; the Teams scopes "
                    "are added to the same OAuth flow."
                ),
            }
        # Validate the token actually has Teams scopes before flipping the
        # channel on. Tenants who connected Outlook before this PR landed
        # will have a token with Mail.* scopes only — calling /me/chats with
        # such a token returns 403, which (without this probe) would let
        # enable() succeed silently and then have every later Teams call
        # fail. Surface the scope mismatch up front.
        ok, reason = await self._probe_teams_scope(token)
        if not ok:
            return {"enabled": False, "reason": reason}
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
            # Reset the monitor cursor + dedup set — re-enabling shouldn't
            # silently replay messages from the disable gap. The next
            # enable starts polling from "now - 5min" via the default in
            # monitor_tick.
            cfg = dict(acct.config or {})
            cfg.pop("last_polled_at", None)
            cfg.pop("processed_ids", None)
            acct.config = cfg
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(acct, "config")
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
        """List the user's recent Teams chats (1:1 + group).

        Follows Graph pagination via ``@odata.nextLink`` up to
        ``_LIST_CHATS_CAP`` items, so tenants with hundreds of chats don't
        get silently truncated.
        """
        token = self._get_access_token(tenant_id)
        if not token:
            return []
        out: list[dict] = []
        url: Optional[str] = f"{GRAPH_BASE}/me/chats"
        params: Optional[dict] = {"$top": 50}
        async with httpx.AsyncClient(timeout=15.0) as client:
            while url and len(out) < _LIST_CHATS_CAP:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
                if resp.status_code >= 300:
                    logger.warning(
                        "Teams list_chats failed for tenant %s: %s %s",
                        str(tenant_id)[:8], resp.status_code, resp.text[:200],
                    )
                    return out
                payload = resp.json() or {}
                out.extend(payload.get("value") or [])
                url = payload.get("@odata.nextLink")
                params = None  # nextLink already encodes the params
        return out[:_LIST_CHATS_CAP]

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
        cap = min(max_results or _FETCH_MESSAGES_CAP, _FETCH_MESSAGES_CAP)
        params: Optional[dict[str, Any]] = {"$top": min(cap, 50)}
        if since_iso:
            # Graph filter on createdDateTime for getAllMessages
            params["$filter"] = f"createdDateTime gt {since_iso}"
        out: list[dict] = []
        url: Optional[str] = f"{GRAPH_BASE}/me/chats/getAllMessages"
        async with httpx.AsyncClient(timeout=20.0) as client:
            while url and len(out) < cap:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
                if resp.status_code >= 300:
                    logger.warning(
                        "Teams fetch_recent_messages failed for tenant %s: %s %s",
                        str(tenant_id)[:8], resp.status_code, resp.text[:200],
                    )
                    return out
                payload = resp.json() or {}
                out.extend(payload.get("value") or [])
                url = payload.get("@odata.nextLink")
                params = None
        return out[:cap]

    async def send_chat_message(
        self,
        tenant_id: str,
        chat_id: str,
        text: str,
        *,
        invoked_by_user_id: Optional[str] = None,
    ) -> dict:
        """POST a message to a 1:1 or group chat by chat_id.

        Note on the allowlist: outbound API send is tenant-authenticated (a
        user pressed "send" through the platform), so we don't gate it on
        ``acct.allow_from``. The allowlist applies to *inbound* auto-reply
        in ``monitor_tick`` — that's where unsolicited DMs from external
        senders need to be filtered. Each successful send is written to the
        agent_audit_log so spam is at least observable.
        """
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
            self._audit_send(
                tenant_id, invoked_by_user_id, chat_id, text,
                status="error", status_code=resp.status_code, body=resp.text,
            )
            return {"sent": False, "status_code": resp.status_code, "body": resp.text[:2000]}
        msg_id = (resp.json() or {}).get("id")
        self._audit_send(
            tenant_id, invoked_by_user_id, chat_id, text,
            status="success", status_code=resp.status_code, body=msg_id or "",
        )
        return {"sent": True, "id": msg_id}

    @staticmethod
    def _audit_send(
        tenant_id: str,
        invoked_by_user_id: Optional[str],
        target: str,
        text: str,
        *,
        status: str,
        status_code: int,
        body: str,
    ) -> None:
        """Fire-and-forget audit log entry for a Teams send.

        Stores the chat/team target (truncated), text length and SHA-256
        prefix (NOT the full body — Teams content can include sensitive
        org info), and Graph response status. Audit log table is shared
        with agent invocations; ``invocation_type="api"`` matches the
        send semantics.
        """
        import hashlib
        try:
            from app.services.audit_log import write_audit_log
            text_hash = hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
            input_summary = f"teams:{target[:64]} len={len(text or '')} sha256={text_hash}"
            user_uuid = None
            if invoked_by_user_id:
                try:
                    import uuid as _uuid
                    user_uuid = _uuid.UUID(str(invoked_by_user_id))
                except Exception:
                    user_uuid = None
            tenant_uuid = None
            try:
                import uuid as _uuid
                tenant_uuid = _uuid.UUID(str(tenant_id))
            except Exception:
                # Audit log requires a UUID tenant_id — skip rather than
                # log under the wrong shape.
                return
            write_audit_log(
                tenant_id=tenant_uuid,
                invoked_by_user_id=user_uuid,
                invocation_type="api",
                input_summary=input_summary,
                output_summary=str(body)[:500],
                status=status,
            )
        except Exception:
            # Audit failures must never break a send.
            pass

    async def send_channel_message(
        self,
        tenant_id: str,
        team_id: str,
        channel_id: str,
        text: str,
        *,
        invoked_by_user_id: Optional[str] = None,
    ) -> dict:
        """POST a message to a Team channel."""
        token = self._get_access_token(tenant_id)
        if not token:
            return {"sent": False, "reason": "no graph token"}
        body = {"body": {"contentType": "text", "content": text}}
        url = f"{GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages"
        target = f"team:{team_id[:12]}/{channel_id[:12]}"
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
            self._audit_send(
                tenant_id, invoked_by_user_id, target, text,
                status="error", status_code=resp.status_code, body=resp.text,
            )
            return {"sent": False, "status_code": resp.status_code, "body": resp.text[:2000]}
        msg_id = (resp.json() or {}).get("id")
        self._audit_send(
            tenant_id, invoked_by_user_id, target, text,
            status="success", status_code=resp.status_code, body=msg_id or "",
        )
        return {"sent": True, "id": msg_id}

    # ── poll-driven monitor entry point ──────────────────────────────

    async def monitor_tick(
        self, tenant_id: str, account_id: str = "default"
    ) -> dict:
        """One iteration of the Teams Monitor — idempotent + allowlist-gated.

        Replies to inbound chat messages addressed to the user via Graph,
        running each through the platform chat path. The two non-obvious
        invariants:

          * **Idempotent over restarts.** We dedup on Graph chatMessage IDs
            (kept in ``acct.config.processed_ids``, capped to the most
            recent ``_PROCESSED_IDS_CAP``) and advance the cursor to the
            ``max(createdDateTime)`` we observed in this poll, not
            ``now()``. This means re-running the tick after a crash will
            re-fetch the same window, the dedup set will short-circuit
            already-replied messages, and no inbound is ever lost in the
            gap between fetch and cursor write.
          * **Fail-closed on self-id.** If we can't fetch
            ``/me?$select=id`` we ABORT the tick rather than processing
            messages, because without ``my_id`` we can't tell our own
            messages from inbound — fail-open here would auto-reply to our
            own posts and create a bot loop.

        Returns counts of fetched / replied / skipped-dedup / blocked for
        observability and structured logs.
        """
        # ── 1. Load account state, abort if not enabled ────────────────
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
            processed_ids: list[str] = list(cfg.get("processed_ids") or [])
            allow_from_snapshot = list(acct.allow_from or [])
            dm_policy_snapshot = (acct.dm_policy or "allowlist").lower()
        finally:
            db.close()

        # Default cursor: fetch the last 5 minutes if no prior poll.
        if not since:
            from datetime import timedelta as _td
            since = (datetime.now(timezone.utc) - _td(minutes=5)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        # ── 2. Identify ourselves — fail closed if Graph won't tell us ─
        token = self._get_access_token(tenant_id)
        if not token:
            return {"ok": False, "reason": "no graph token"}
        my_id: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                me = await client.get(
                    f"{GRAPH_BASE}/me?$select=id",
                    headers={"Authorization": f"Bearer {token}"},
                )
                if me.status_code < 300:
                    my_id = (me.json() or {}).get("id")
        except Exception as e:
            logger.warning(
                "Teams monitor: /me probe raised for tenant %s: %s",
                str(tenant_id)[:8], e,
            )
        if not my_id:
            # Don't fail open. Without my_id we can't distinguish inbound
            # from our own outbound, and a bot loop is much worse than a
            # missed cycle. Cursor is NOT advanced — the next tick will
            # retry the same window.
            logger.warning(
                "Teams monitor: skipping tick for tenant %s — could not "
                "resolve /me id (token may be stale or scope insufficient)",
                str(tenant_id)[:8],
            )
            return {"ok": False, "reason": "self-id probe failed"}

        # ── 3. Fetch + deduplicate ─────────────────────────────────────
        messages = await self.fetch_recent_messages(tenant_id, since_iso=since)
        fetched = len(messages)
        replied = 0
        skipped_dedup = 0
        blocked = 0
        max_seen_dt: Optional[str] = None
        seen_ids: set[str] = set(processed_ids)

        # Build a synthetic ChannelAccount-like object for the allowlist
        # check so we can call _is_sender_allowed without re-reading from
        # the DB on each message (the snapshot above is point-in-time —
        # consistent with a single tick).
        class _AcctView:
            dm_policy = dm_policy_snapshot
            allow_from = allow_from_snapshot

        for msg in messages:
            msg_id = msg.get("id") or ""
            if msg_id and msg_id in seen_ids:
                skipped_dedup += 1
                continue

            sender_user = (msg.get("from") or {}).get("user") or {}
            sender = sender_user.get("id") or ""
            sender_upn = sender_user.get("userPrincipalName") or ""
            if sender == my_id:
                # Our own outbound — record id so we don't re-look at it,
                # but no other action.
                if msg_id:
                    seen_ids.add(msg_id)
                continue

            if not self._is_sender_allowed(_AcctView, sender, sender_upn):
                blocked += 1
                if msg_id:
                    seen_ids.add(msg_id)
                logger.info(
                    "Teams monitor: blocked auto-reply for tenant %s sender=%s (not in allowlist)",
                    str(tenant_id)[:8], (sender_upn or sender)[:64],
                )
                continue

            chat_id = msg.get("chatId")
            text = ((msg.get("body") or {}).get("content") or "").strip()
            created_dt = msg.get("createdDateTime") or ""
            if created_dt and (max_seen_dt is None or created_dt > max_seen_dt):
                max_seen_dt = created_dt
            if not (chat_id and text):
                if msg_id:
                    seen_ids.add(msg_id)
                continue

            response = await self._dispatch_chat_async(
                tenant_id, account_id, sender or "unknown", text, chat_id
            )
            # Mark the inbound message processed BEFORE attempting the
            # send, so if the send raises, the next tick won't auto-reply
            # to the same message a second time. We rely on Teams'
            # at-most-once auto-reply being safer than at-least-once.
            if msg_id:
                seen_ids.add(msg_id)
            if response:
                send_result = await self.send_chat_message(tenant_id, chat_id, response)
                if send_result.get("sent"):
                    replied += 1

        # ── 4. Advance cursor + persist dedup set ──────────────────────
        # Use max(createdDateTime) of fetched messages (so messages
        # arriving DURING the tick are caught next time) and fall back
        # to the prior `since` if no messages were processed (so we
        # don't inadvertently regress the cursor on quiet polls).
        new_cursor = max_seen_dt or since
        # Cap the dedup set; keep the most recent IDs (set order isn't
        # guaranteed, so we sort heuristically by recency-of-insert via
        # the existing ordering then truncate).
        dedup_list = list(seen_ids)
        if len(dedup_list) > _PROCESSED_IDS_CAP:
            dedup_list = dedup_list[-_PROCESSED_IDS_CAP:]

        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            cfg = dict(acct.config or {})
            cfg["last_polled_at"] = new_cursor
            cfg["processed_ids"] = dedup_list
            acct.config = cfg
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(acct, "config")
            db.commit()
        finally:
            db.close()

        return {
            "ok": True,
            "fetched": fetched,
            "replied": replied,
            "skipped_dedup": skipped_dedup,
            "blocked": blocked,
            "cursor": new_cursor,
        }

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
