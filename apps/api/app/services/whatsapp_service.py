"""
WhatsApp channel service using neonize (whatsmeow Go backend).
Manages per-tenant WhatsApp Web sessions directly in the FastAPI process.
"""
import asyncio
import base64
import io
import inspect
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

import segno
from sqlalchemy.orm import Session

# Lazy neonize imports — neonize requires protobuf>=7 which conflicts with
# temporalio (protobuf<7). Import at use-time only.
NewAClient = None
ConnectedEv = DisconnectedEv = LoggedOutEv = MessageEv = PairStatusEv = None
build_jid = None
ChatPresence = ChatPresenceMedia = None

def _ensure_neonize():
    """Lazy-load neonize on first use. Raises ImportError if unavailable."""
    global NewAClient, ConnectedEv, DisconnectedEv, LoggedOutEv, MessageEv, PairStatusEv
    global build_jid, ChatPresence, ChatPresenceMedia
    if NewAClient is not None:
        return
    from neonize.aioze.client import NewAClient as _NewAClient
    from neonize.aioze.events import (
        ConnectedEv as _ConnectedEv,
        DisconnectedEv as _DisconnectedEv,
        LoggedOutEv as _LoggedOutEv,
        MessageEv as _MessageEv,
        PairStatusEv as _PairStatusEv,
    )
    from neonize.utils import build_jid as _build_jid
    from neonize.utils.enum import ChatPresence as _ChatPresence, ChatPresenceMedia as _ChatPresenceMedia
    NewAClient = _NewAClient
    ConnectedEv = _ConnectedEv
    DisconnectedEv = _DisconnectedEv
    LoggedOutEv = _LoggedOutEv
    MessageEv = _MessageEv
    PairStatusEv = _PairStatusEv
    build_jid = _build_jid
    ChatPresence = _ChatPresence
    ChatPresenceMedia = _ChatPresenceMedia

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.channel_account import ChannelAccount
from app.models.channel_event import ChannelEvent
from app.models.whatsapp_session_backup import WhatsappSessionBackup
from app.models.chat import ChatSession
from app.services.url_intent_router import extract_learning_url

logger = logging.getLogger(__name__)

WHATSAPP_AUDIO_TRANSCRIBE_TIMEOUT_SECONDS = 60.0
DEFAULT_WHATSAPP_AUDIO_MIME = "audio/ogg"
WHATSAPP_AUDIO_TRANSCRIPTION_FALLBACK = (
    "[User sent a WhatsApp voice message, but the audio could not be "
    "transcribed. Apologize briefly and ask them to resend the voice note "
    "or type the message.]"
)

# ── Fire-and-forget chat dispatch (thread-pool wedge fix, 2026-06-04) ──
# WhatsApp turns run on a DEDICATED bounded executor (never the shared event-
# loop default pool) so a slow/hung turn can't starve the rest of the api. An
# explicit capacity gate (global + per-sender) bounds the in-memory queue so a
# burst can't pile up. Delivery is fire-and-forget: the inbound handler
# enqueues and returns; a per-sender single-consumer task runs the turn,
# keeps "typing…" alive, and sends the reply in order.
# WHATSAPP_JOB_WATCH_TIMEOUT is a backstop ABOVE the CLI dispatch bound
# (CHAT_CLI_DISPATCH_TIMEOUT, default 600s) — the dispatch self-terminates
# first, so the watch rarely fires.
WHATSAPP_CHAT_WORKERS = int(os.environ.get("WHATSAPP_CHAT_WORKERS", "4"))
WHATSAPP_CHAT_GLOBAL_CAP = int(os.environ.get("WHATSAPP_CHAT_GLOBAL_CAP", "16"))
WHATSAPP_CHAT_PER_SENDER_CAP = int(os.environ.get("WHATSAPP_CHAT_PER_SENDER_CAP", "4"))
WHATSAPP_JOB_WATCH_TIMEOUT = float(os.environ.get("WHATSAPP_JOB_WATCH_TIMEOUT", "660"))
WHATSAPP_TURN_FAILED_FALLBACK = (
    "Sorry — I hit an error processing that. Please try again in a moment."
)
WHATSAPP_OVERLOADED_FALLBACK = (
    "I'm a bit overloaded right now — please resend that in a moment."
)
WHATSAPP_RESTART_FALLBACK = (
    "I'm restarting briefly — please resend your last message in a moment."
)


@dataclass
class _WaChatTurn:
    """One queued WhatsApp chat turn (the fire-and-forget unit)."""
    queue_key: str          # ordering key: f"{account_key}::{sender_id}"
    account_key: str        # client-lookup key: f"{tenant_id}:{account_id}"
    tenant_id: uuid.UUID
    tenant_id_str: str
    account_id: str
    sender_phone: str
    reply_jid: object       # neonize JID from build_jid
    job_uuid: uuid.UUID
    session_id: uuid.UUID
    user_id: uuid.UUID
    content: str
    media_parts: Optional[list] = None


def _detect_inbound_media(msg, text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return media type, MIME type, and caption for an inbound WhatsApp message."""
    image = getattr(msg, "imageMessage", None)
    if image and getattr(image, "mimetype", None):
        return "image", image.mimetype, getattr(image, "caption", None) or text

    audio = getattr(msg, "audioMessage", None)
    # CRITICAL: protobuf3 message fields default to a present-but-empty
    # sub-message, so `if audio:` is True even when no audio was sent.
    # That mis-classified every WhatsApp inbound (including pure text
    # messages like "Ping") as audio → WHATSAPP_AUDIO_TRANSCRIPTION_
    # FALLBACK fired on every chat turn → Luna's session filled up
    # with "Sorry baby, I couldn't transcribe…" apologies even for
    # plain text. Diagnosed 2026-05-24 from chat_messages history:
    # text going back to 17:54 UTC all show the fallback instruction
    # stored as user content instead of the actual text.
    #
    # Fix: require at least ONE actual audio-payload field (mimetype,
    # fileLength, mediaKey, or directPath) to consider this a real
    # audio message. Mirrors the image-detection pattern above which
    # already requires `image.mimetype`.
    if audio and (
        getattr(audio, "mimetype", None)
        or getattr(audio, "fileLength", 0)
        or getattr(audio, "mediaKey", b"")
        or getattr(audio, "directPath", "")
    ):
        return "audio", getattr(audio, "mimetype", None) or DEFAULT_WHATSAPP_AUDIO_MIME, text

    document = getattr(msg, "documentMessage", None)
    if document and getattr(document, "mimetype", None):
        caption = getattr(document, "title", None) or getattr(document, "fileName", None) or text
        return "document", document.mimetype, caption

    # T4.2 — text-only message may contain a learning URL (YouTube / IG).
    # When matched, surface as a new ``learning_url`` tuple variant so the
    # caller can route to LearningService.dispatch instead of the normal
    # chat/agent pipeline. mime slot carries the URL itself; caption keeps
    # the original message text so Luna's ack can quote / contextualize it.
    learning_url = extract_learning_url(text)
    if learning_url:
        return "learning_url", learning_url, text

    return None, None, text


def _phone_variants(value: str | None) -> set[str]:
    """Return normalized phone variants for allowlist matching.

    Handles WhatsApp JIDs/domains, leading plus signs, and Mexico mobile
    numbers which may appear as either 52... or 521....
    """
    if not value:
        return set()

    base = value.split("@", 1)[0].strip()
    digits = "".join(ch for ch in base if ch.isdigit())
    variants = {base, base.lstrip("+"), digits}

    # Mexico mobile: 52... -> 521... and vice-versa
    if digits.startswith("521") and len(digits) > 3:
        variants.add("52" + digits[3:])
    elif digits.startswith("52") and not digits.startswith("521") and len(digits) > 2:
        variants.add("521" + digits[2:])
    
    # General: If digits starts with country code but no plus, add plus variant
    # and vice-versa if it was provided with plus
    if digits and not value.startswith("+"):
        variants.add("+" + digits)

    return {item for item in variants if item}


import random as _random

def _build_ack_message(user_message: str, task_type: str) -> str:
    """Build a natural, conversational acknowledgment."""
    acks = {
        "code": _random.choice([
            "Let me look at the code",
            "Ok checking that out",
            "Let me dig into the code for you",
            "On it, pulling up the repo",
        ]),
        "research": _random.choice([
            "Let me look into that",
            "Good question, let me find out",
            "Give me a sec, checking my sources",
            "Ok let me research that for you",
        ]),
        "email": _random.choice([
            "Let me check your emails",
            "One sec, looking through your inbox",
            "Ok pulling up your emails",
        ]),
        "calendar": _random.choice([
            "Let me check your calendar",
            "One sec, looking at your schedule",
            "Ok checking that",
        ]),
        "sales": _random.choice([
            "Let me pull up the pipeline",
            "Ok checking the deals",
            "One sec, looking at the numbers",
        ]),
        "data": _random.choice([
            "Let me check the data",
            "Ok running that query",
            "Give me a moment, pulling the numbers",
        ]),
    }
    default = _random.choice([
        "Ok let me see",
        "Let me check that for you",
        "One sec",
        "Let's find out",
        "On it",
        "Give me a moment",
        "Let me look into that",
    ])
    return acks.get(task_type, default)


_PROGRESS_MESSAGES = [
    "Still working on it",
    "Taking a bit longer than usual",
    "Almost there",
    "This one's a bit involved, hang tight",
    "Still going",
    "Bear with me",
    "Nearly done",
]

def _get_progress_message(tick: int) -> str:
    """Get a rotating progress message based on elapsed ticks."""
    return _PROGRESS_MESSAGES[tick % len(_PROGRESS_MESSAGES)]


class WhatsAppService:
    """Manages neonize WhatsApp clients per tenant:account."""

    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_BASE_DELAY = 2  # seconds, doubles each attempt

    # 2026-05-20 Option-A hardening (whatsapp-api-research.md §"Stay on
    # neonize + harden"). Three thresholds gate the new safety nets:
    STABLE_CONNECTION_SECONDS = 30  # connection must hold this long
    # before the reconnect counter resets — otherwise a 2-second
    # connect-disconnect flap (the failure mode we hit 2026-05-19
    # repeatedly) keeps restarting at base delay instead of escalating.
    HEARTBEAT_INTERVAL_SECONDS = 30  # IsConnected() poll cadence.
    HEARTBEAT_TIMEOUT_SECONDS = 5    # asyncio.wait_for guard — if the
    # Go callback hangs longer than this, treat as silent socket death.

    def __init__(self, db_url: str):
        _ensure_neonize()
        self._clients: Dict[str, NewAClient] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._watchdog_tasks: Dict[str, asyncio.Task] = {}
        self._heartbeat_tasks: Dict[str, asyncio.Task] = {}
        self._stable_reset_tasks: Dict[str, asyncio.Task] = {}
        self._qr_codes: Dict[str, str] = {}
        self._statuses: Dict[str, str] = {}
        self._reconnect_counts: Dict[str, int] = {}
        # asyncio.Lock per account-key to serialize SQLite session
        # save/restore. Eliminates the concurrent-writer race that
        # corrupts the on-disk DB and produces the
        # "database disk image is malformed" decryption failures
        # documented in whatsapp_sqlite_corruption_recovery.md.
        self._session_locks: Dict[str, asyncio.Lock] = {}
        self._sent_message_ids: Dict[str, set] = {}  # Track bot-sent msg IDs to avoid echo loops
        self._lid_phone_cache: Dict[str, str] = {}  # LID→phone cache for resolved numbers
        self._db_url = db_url
        # ── Graceful-drain coordination (session-durability design §1/§5) ──
        # `_draining` gates new inbound chat turns once shutdown begins;
        # `_inflight_turns` counts turns running in the thread pool so the
        # drain can bounded-wait for them instead of a blind stop grace
        # that truncates the 30–90s turns the 180s grace existed to protect.
        self._draining: bool = False
        self._inflight_turns: int = 0
        # Rolling known-good session backups kept per account in Postgres
        # (whatsapp_session_backups). Restore falls back through these so a
        # corrupt/mid-write current blob never forces a QR re-pair.
        self.SESSION_BACKUP_KEEP: int = int(
            os.environ.get("WHATSAPP_SESSION_BACKUP_KEEP", "3")
        )
        # ── Fire-and-forget chat dispatch state (2026-06-04 wedge fix) ──
        # Dedicated bounded pool so a slow/hung WhatsApp turn can never starve
        # the shared event-loop default executor the rest of the api uses.
        from concurrent.futures import ThreadPoolExecutor as _TPE
        self._chat_executor = _TPE(
            max_workers=WHATSAPP_CHAT_WORKERS, thread_name_prefix="wa-chat",
        )
        self._chat_queues: Dict[str, asyncio.Queue] = {}   # ordering key -> pending turns
        self._chat_consumers: Dict[str, asyncio.Task] = {}  # ordering key -> consumer task
        self._chat_active: Dict[str, _WaChatTurn] = {}      # ordering key -> mid-flight turn
        self._chat_inflight_global: int = 0                 # capacity gate (enqueued, not done)
        self._chat_dispatch_lock = asyncio.Lock()           # guards the maps + the gate

    def _purge_local_session_file(
        self, tenant_id: str, account_id: str, *, reason: str
    ) -> None:
        """Delete the on-disk neonize SQLite session file for this
        account so the next `start_pairing` has no credentials to
        rehydrate and mints a fresh QR.

        Called from `disable()` and `logout()`. Without this, those
        endpoints clear the in-memory client + DB status but leave the
        device credentials on disk, so when the user next clicks Link
        Phone the api silently reconnects with the existing credentials
        and never shows a QR — the failure mode the operator hit 4+
        times on 2026-05-20.

        Best-effort: never raises into the caller. If the file is
        already absent (already purged, never created, or another
        concurrent op cleared it) the function is a no-op. Backups
        created earlier in the session (e.g. .corrupt-backup,
        .pre-repair) are not touched.
        """
        try:
            path = self._client_name(tenant_id, account_id)
            if os.path.exists(path):
                os.remove(path)
                logger.info(
                    "Purged neonize session file (%s): %s", reason, path
                )
            else:
                logger.debug(
                    "_purge_local_session_file: no file at %s (already gone)",
                    path,
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to purge neonize session file for %s:%s (%s)",
                tenant_id, account_id, reason,
            )

    def _get_session_lock(self, key: str) -> asyncio.Lock:
        """Fetch-or-create the per-account asyncio.Lock used to
        serialize SQLite session save/restore. Safe to call from any
        async context; the dict insert is single-threaded under
        asyncio's cooperative model so no further synchronization is
        needed for the dict itself."""
        lock = self._session_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[key] = lock
        return lock

    async def _save_session_locked(
        self, tenant_id: str, account_id: str, source_event: str = "runtime"
    ) -> None:
        """Async lock wrapper around `_save_session_to_db`. All async
        event-handler call sites (on_connected, on_disconnected,
        on_paired) go through this; the lock serializes them against
        any concurrent _restore_session_from_db on the same key.

        Best-effort: the underlying save can still raise; we let it
        propagate so existing error paths (which currently swallow) keep
        their semantics. The lock only prevents the race, not the
        exception."""
        key = self._key(tenant_id, account_id)
        async with self._get_session_lock(key):
            # `_save_session_to_db` is synchronous SQLite work + sync
            # SQLAlchemy call; running it directly inside the async
            # handler is fine — it's bounded (≤ a few hundred ms for
            # the 7MB-class blob we've seen in production).
            self._save_session_to_db(tenant_id, account_id, source_event=source_event)

    async def _socket_heartbeat(self, tenant_id: str, account_id: str) -> None:
        """Background coroutine that polls `client.IsConnected()` every
        HEARTBEAT_INTERVAL_SECONDS. If the call returns False or hangs
        beyond HEARTBEAT_TIMEOUT_SECONDS (silent socket death — the
        whatsmeow event loop has wedged without firing DisconnectedEv),
        trip the existing auto-reconnect path.

        This is the Option-A core fix from
        docs/plans/2026-05-18-whatsapp-api-research.md §"Stay on
        neonize + harden": catches the silent-disconnect failure mode
        that the existing DisconnectedEv-driven reconnect cannot see.

        The task is started in connect_account and torn down on
        explicit disconnect / logout. It MUST not raise into the event
        loop — catch everything and log."""
        key = self._key(tenant_id, account_id)
        logger.info(f"_socket_heartbeat started for {key}")
        try:
            while True:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL_SECONDS)
                status = self._statuses.get(key)
                if status in ("logged_out", "disconnected", None):
                    # Status went terminal — heartbeat owner stops.
                    logger.info(f"_socket_heartbeat exiting for {key} (status={status})")
                    return
                client = self._clients.get(key)
                if client is None:
                    logger.info(f"_socket_heartbeat exiting for {key} (no client)")
                    return
                try:
                    # neonize exposes `is_connected` as a PROPERTY
                    # (verified 2026-05-20 via
                    # `type(getattr(NewAClient, 'is_connected'))` →
                    # `<class 'property'>`). Accessing the attribute
                    # returns the property's getter result — which is
                    # itself a coroutine in the async client build, NOT
                    # a callable. Do not add parens. Then check
                    # awaitable / coerce to bool as before.
                    res = client.is_connected
                    if inspect.isawaitable(res):
                        is_connected = await asyncio.wait_for(
                            res, timeout=self.HEARTBEAT_TIMEOUT_SECONDS,
                        )
                    else:
                        is_connected = bool(res)
                except asyncio.TimeoutError:
                    logger.warning(
                        f"_socket_heartbeat: IsConnected() hung > "
                        f"{self.HEARTBEAT_TIMEOUT_SECONDS}s for {key} — "
                        "treating as silent socket death; tripping reconnect"
                    )
                    self._statuses[key] = "disconnected"
                    self._update_account_status(tenant_id, account_id, "disconnected")
                    asyncio.ensure_future(self._auto_reconnect(tenant_id, account_id))
                    return
                except Exception:  # noqa: BLE001
                    logger.exception(f"_socket_heartbeat: IsConnected() raised for {key}")
                    # Don't trip reconnect on a single weird exception
                    # — could be a transient FFI hiccup. Next tick
                    # decides.
                    continue
                if not is_connected:
                    logger.warning(
                        f"_socket_heartbeat: IsConnected()=False for {key} — "
                        "tripping reconnect"
                    )
                    self._statuses[key] = "disconnected"
                    self._update_account_status(tenant_id, account_id, "disconnected")
                    asyncio.ensure_future(self._auto_reconnect(tenant_id, account_id))
                    return
        except asyncio.CancelledError:
            return

    def _start_heartbeat(self, tenant_id: str, account_id: str) -> None:
        """Cancel any existing heartbeat for this key + start a fresh
        one. Called from on_connected. Idempotent."""
        key = self._key(tenant_id, account_id)
        prev = self._heartbeat_tasks.pop(key, None)
        if prev and not prev.done():
            prev.cancel()
        self._heartbeat_tasks[key] = asyncio.ensure_future(
            self._socket_heartbeat(tenant_id, account_id)
        )

    async def _delayed_counter_reset(self, key: str) -> None:
        """Reset _reconnect_counts[key] to 0 ONLY after the connection
        has been continuously up for STABLE_CONNECTION_SECONDS. If a
        disconnect fires before this delay elapses, the task is
        cancelled and the counter keeps its escalated value — so the
        next reconnect uses the proper backoff delay instead of
        restarting at base.

        Without this, the 2026-05-19 incident pattern (every reconnect
        succeeds for 2-3s then dies) hammered WhatsApp's server every
        ~2s and got nowhere."""
        try:
            await asyncio.sleep(self.STABLE_CONNECTION_SECONDS)
            self._reconnect_counts[key] = 0
            logger.debug(
                f"Stable-connection threshold reached for {key} "
                f"({self.STABLE_CONNECTION_SECONDS}s) — reconnect "
                "counter reset"
            )
        except asyncio.CancelledError:
            return

    WHATSAPP_CONNECT_TIMEOUT = 5  # seconds for pre-flight check

    def _key(self, tenant_id: str, account_id: str = "default") -> str:
        return f"{tenant_id}:{account_id}"

    @staticmethod
    def _is_whatsapp_reachable(timeout: int = 5) -> bool:
        """Pre-flight TCP check to web.whatsapp.com:443.

        Neonize's Go code panics (kills process) on TLS handshake timeout,
        so we verify network connectivity before calling client.connect().
        """
        try:
            sock = socket.create_connection(("web.whatsapp.com", 443), timeout=timeout)
            sock.close()
            return True
        except (OSError, socket.timeout):
            return False

    def _client_name(self, tenant_id: str, account_id: str = "default") -> str:
        # Use persistent storage so sessions survive pod restarts
        base = settings.DATA_STORAGE_PATH or "/app/storage"
        session_dir = os.environ.get("NEONIZE_SESSION_DIR", f"{base}/neonize_sessions")
        os.makedirs(session_dir, exist_ok=True)
        short = tenant_id[:8]
        return f"{session_dir}/wa_{short}_{account_id}.db"

    # ── DB helpers ────────────────────────────────────────────────────

    def _get_db(self) -> Session:
        return SessionLocal()

    def _get_or_create_account(
        self, db: Session, tenant_id: str, account_id: str = "default",
    ) -> ChannelAccount:
        tid = uuid.UUID(tenant_id)
        acct = (
            db.query(ChannelAccount)
            .filter(
                ChannelAccount.tenant_id == tid,
                ChannelAccount.channel_type == "whatsapp",
                ChannelAccount.account_id == account_id,
            )
            .first()
        )
        if not acct:
            acct = ChannelAccount(
                tenant_id=tid,
                channel_type="whatsapp",
                account_id=account_id,
            )
            db.add(acct)
            try:
                db.flush()
                db.refresh(acct)
            except Exception:
                db.rollback()
                raise
        return acct

    def _update_account_status(
        self, tenant_id: str, account_id: str, status: str,
        error: Optional[str] = None, phone: Optional[str] = None,
    ):
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            acct.status = status
            acct.updated_at = datetime.utcnow()
            if error is not None:
                acct.last_error = error
            if phone is not None:
                acct.phone_number = phone
            if status == "connected":
                acct.connected_at = datetime.utcnow()
                acct.reconnect_attempts = 0
                acct.last_error = None
            elif status == "disconnected":
                acct.disconnected_at = datetime.utcnow()
            db.commit()
        except Exception:
            logger.exception("Failed to update account status")
            db.rollback()
        finally:
            db.close()

    def _log_event(
        self, tenant_id: str, account_id: str, event_type: str,
        direction: Optional[str] = None, remote_id: Optional[str] = None,
        message_content: Optional[str] = None, extra_data: Optional[dict] = None,
    ):
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            evt = ChannelEvent(
                tenant_id=uuid.UUID(tenant_id),
                channel_account_id=acct.id,
                event_type=event_type,
                direction=direction,
                remote_id=remote_id,
                message_content=message_content,
                extra_data=extra_data or {},
            )
            db.add(evt)
            db.commit()
        except Exception:
            logger.exception("Failed to log channel event")
            db.rollback()
        finally:
            db.close()

    # ── Session blob persistence ────────────────────────────────────

    # ── Session validation (the recover-never-QR contract, design §2) ──
    _SQLITE_MAGIC = b"SQLite format 3\x00"

    def _validate_sqlite_bytes(self, raw: bytes) -> tuple:
        """Validate that `raw` is a healthy neonize device session.

        Returns (ok: bool, reason: str). `ok` is True only when:
          * the bytes carry the SQLite file magic header,
          * `PRAGMA integrity_check` returns 'ok',
          * the device-key assertion holds — a whatsmeow device table
            exists with >= 1 row (a structurally-valid but keyless DB is
            useless and would still force a QR; Codex-5.5 review #3/#answer-2).

        A blob with NO recognised device table is a HARD FAIL (review
        C2-VALIDATE-FALSE-POSITIVE): a keyless / partially-initialised /
        unrecognised-schema blob must never be promoted to the validated
        current or an 'ok' backup. Keeping the last known-good is always
        safer than persisting a session we cannot prove carries auth keys.
        """
        import sqlite3
        import tempfile
        if not raw or not raw.startswith(self._SQLITE_MAGIC):
            return False, "not a sqlite file (bad magic header)"
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".db", prefix="wa_validate_")
            os.close(fd)
            with open(tmp, "wb") as f:
                f.write(raw)
            conn = sqlite3.connect(tmp, timeout=5)
            try:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                result = str(row[0]).lower() if row else "no result"
                if result != "ok":
                    return False, f"integrity_check failed: {result}"
                tables = [
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                ]
                # Broad match: a real neonize session carries a `whatsmeow_device`
                # table. Match any table whose name contains "device" to be
                # robust to store-layout naming, then require >= 1 row.
                device_tables = [t for t in tables if "device" in t.lower()]
                if not device_tables:
                    return False, "no device table found (keyless or unrecognised schema)"
                total = 0
                for t in device_tables:
                    try:
                        c = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()
                        total += int(c[0]) if c else 0
                    except Exception:  # noqa: BLE001
                        pass
                if total < 1:
                    return False, f"device table(s) {device_tables} empty (no auth keys)"
                return True, "ok"
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            return False, f"validation error: {e}"
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except Exception:  # noqa: BLE001
                    pass

    def _prune_session_backups(self, db, tenant_uuid, account_id: str, keep: int) -> int:
        """Keep only the newest `keep` validated ('ok') backups per account.
        Assumes the just-added row has been flushed so it's included in the
        ordering. Returns the number of rows deleted.

        Intentionally prunes only validation_status=='ok' rows — the writer
        only ever inserts 'ok' (review FG-3); 'pending'/'corrupt' are reserved
        for future diagnostics and, if ever written, would need their own
        cap/expiry here so they can't accumulate unbounded."""
        rows = (
            db.query(WhatsappSessionBackup)
            .filter(
                WhatsappSessionBackup.tenant_id == tenant_uuid,
                WhatsappSessionBackup.account_id == account_id,
                WhatsappSessionBackup.validation_status == "ok",
            )
            .order_by(WhatsappSessionBackup.created_at.desc(), WhatsappSessionBackup.id.desc())
            .all()
        )
        deleted = 0
        for old in rows[max(keep, 0):]:
            db.delete(old)
            deleted += 1
        return deleted

    def _save_session_to_db(self, tenant_id: str, account_id: str, source_event: str = "runtime") -> bool:
        """Persist the neonize SQLite session as the VALIDATED current blob,
        push a rolling known-good backup, and prune.

        This is the inverse of the old "corruption amplifier" (design §2):
        it NEVER overwrites a known-good current/backup with an unvalidated
        blob. Returns True iff a validated blob was persisted. On checkpoint
        failure (DB locked / mid-write) or validation failure it ABORTS the
        write, preserving the last known-good copy, and logs loudly.
        """
        import gzip
        import hashlib
        import sqlite3
        path = self._client_name(tenant_id, account_id)
        if not os.path.exists(path):
            return False

        # 1. Checkpoint MUST actually COMPLETE — not merely return. A
        #    locked/mid-write DB means the file may be inconsistent; abort
        #    rather than persist a torn snapshot.
        try:
            conn = sqlite3.connect(path, timeout=5)
            try:
                ckpt = conn.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "WhatsApp save ABORTED for %s:%s — checkpoint raised (DB locked / mid-write): %s. "
                "Keeping last known-good session, no overwrite.",
                tenant_id[:8], account_id, e,
            )
            return False
        # PRAGMA wal_checkpoint(FULL) returns (busy, log_frames, checkpointed).
        # busy != 0 means it could NOT merge all WAL frames into the main .db
        # (another connection held it) — so the .db we're about to read is
        # missing the latest writes. "Returned" is not "completed" (review):
        # abort and keep the last known-good rather than persist a stale/torn
        # snapshot. busy == 0 with log == -1 (no WAL in use) is success.
        busy = ckpt[0] if ckpt else 1
        if busy != 0:
            logger.warning(
                "WhatsApp save ABORTED for %s:%s — WAL checkpoint incomplete "
                "(busy=%s, result=%s); keeping last known-good, no overwrite.",
                tenant_id[:8], account_id, busy, ckpt,
            )
            return False

        # 2. Read + validate. Only a healthy SQLite becomes the new current.
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception:
            logger.exception(
                "WhatsApp save ABORTED for %s:%s — could not read session file (no overwrite)",
                tenant_id[:8], account_id,
            )
            return False

        ok, reason = self._validate_sqlite_bytes(raw)
        if not ok:
            logger.warning(
                "WhatsApp save ABORTED for %s:%s — session failed validation (%s). "
                "Keeping last known-good, no overwrite.",
                tenant_id[:8], account_id, reason,
            )
            return False

        sha = hashlib.sha256(raw).hexdigest()
        compressed = gzip.compress(raw)

        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            latest = (
                db.query(WhatsappSessionBackup)
                .filter(
                    WhatsappSessionBackup.tenant_id == acct.tenant_id,
                    WhatsappSessionBackup.account_id == account_id,
                    WhatsappSessionBackup.validation_status == "ok",
                )
                .order_by(
                    WhatsappSessionBackup.created_at.desc(),
                    WhatsappSessionBackup.id.desc(),  # stable tiebreaker (MTR-5)
                )
                .first()
            )
            # Validated current pointer.
            acct.session_blob = compressed
            pruned = 0
            if latest is None or latest.sha256 != sha:
                db.add(WhatsappSessionBackup(
                    tenant_id=acct.tenant_id,
                    account_id=account_id,
                    blob=compressed,
                    sha256=sha,
                    size_bytes=len(raw),
                    validation_status="ok",
                    source_event=source_event,
                ))
                db.flush()  # so the new row is included in the prune ordering
                pruned = self._prune_session_backups(
                    db, acct.tenant_id, account_id, keep=self.SESSION_BACKUP_KEEP
                )
            db.commit()
            logger.info(
                "Saved validated WhatsApp session for %s:%s (%s, %d→%d bytes, sha=%s, pruned=%d)",
                tenant_id[:8], account_id, source_event, len(raw), len(compressed), sha[:8], pruned,
            )
            return True
        except Exception:
            logger.exception(
                "Failed to persist validated WhatsApp session for %s:%s", tenant_id[:8], account_id
            )
            db.rollback()
            return False
        finally:
            db.close()

    def _restore_session_from_db(self, tenant_id: str, account_id: str) -> bool:
        """Restore the neonize SQLite session from the durable Postgres copy,
        preferring the validated CURRENT blob and falling back through the
        rolling known-good backups (design §3).

        Contract: NEVER write an invalid blob to disk, and NEVER force a QR
        for a recoverable corruption — a QR is reached only when every copy
        is unusable (the device was genuinely revoked). Returns True iff a
        validated session was written to disk.
        """
        import gzip
        try:
            # Phase 1 — read candidate blobs into memory, then CLOSE the db
            # session so the slow per-candidate SQLite validation + multi-MB
            # disk write below don't hold a Postgres connection idle-in-
            # transaction (review MTR-6).
            db = self._get_db()
            try:
                acct = self._get_or_create_account(db, tenant_id, account_id)
                tenant_uuid = acct.tenant_id
                candidates = []  # list of (label, is_current, compressed_blob)
                if acct.session_blob:
                    candidates.append(("current", True, acct.session_blob))
                backups = (
                    db.query(WhatsappSessionBackup)
                    .filter(
                        WhatsappSessionBackup.tenant_id == tenant_uuid,
                        WhatsappSessionBackup.account_id == account_id,
                        WhatsappSessionBackup.validation_status == "ok",
                    )
                    # id.desc() is a stable tiebreaker for same-tick created_at
                    # (matches _prune_session_backups; review MTR-5). It does
                    # not encode recency (id is a random uuid) but all tied rows
                    # are equally known-good, so any is safe to restore.
                    .order_by(
                        WhatsappSessionBackup.created_at.desc(),
                        WhatsappSessionBackup.id.desc(),
                    )
                    .all()
                )
                for i, b in enumerate(backups):
                    candidates.append((f"backup#{i}", False, b.blob))
            finally:
                db.close()

            if not candidates:
                logger.info("No WhatsApp session to restore for %s:%s", tenant_id[:8], account_id)
                return False

            path = self._client_name(tenant_id, account_id)
            # Phase 2 — validate best-first; write the first good copy to disk.
            for label, is_current, comp in candidates:
                try:
                    raw = gzip.decompress(comp)
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "WhatsApp restore: %s blob for %s:%s failed to decompress (%s) — trying next",
                        label, tenant_id[:8], account_id, e,
                    )
                    continue
                ok, reason = self._validate_sqlite_bytes(raw)
                if not ok:
                    logger.warning(
                        "WhatsApp restore: %s blob for %s:%s failed validation (%s) — trying next",
                        label, tenant_id[:8], account_id, reason,
                    )
                    continue
                # Write the validated copy. Delete any stale WAL/SHM first
                # (SQLite refuses to open a .db with an inconsistent WAL).
                os.makedirs(os.path.dirname(path), exist_ok=True)
                for suffix in ("-wal", "-shm"):
                    try:
                        os.remove(path + suffix)
                    except FileNotFoundError:
                        pass
                    except Exception:  # noqa: BLE001
                        logger.warning("Failed to delete stale %s file %s", suffix, path + suffix)
                with open(path, "wb") as f:
                    f.write(raw)
                if is_current:
                    logger.info(
                        "Restored WhatsApp session for %s:%s from current (%d bytes)",
                        tenant_id[:8], account_id, len(raw),
                    )
                else:
                    # Self-heal: promote the recovered backup to current so the
                    # next restore is fast and the corrupt current is replaced.
                    # Intentionally lockless: this runs at startup / readonly
                    # auto-restore, and the per-account session lock is NOT a
                    # global save barrier anyway (the pairing-status and active-
                    # probe save paths also persist unlocked); worst case is a
                    # last-writer-wins refresh that self-corrects on the next
                    # event-driven save (review MTR-2). The disk is already
                    # healed (write above), so reconnect succeeds with NO QR
                    # regardless of whether this promote commits.
                    logger.warning(
                        "WhatsApp restore: recovered %s:%s from %s (current was unusable) "
                        "— self-healed from backup, NO QR",
                        tenant_id[:8], account_id, label,
                    )
                    hdb = self._get_db()
                    try:
                        hacct = self._get_or_create_account(hdb, tenant_id, account_id)
                        hacct.session_blob = comp
                        hdb.commit()
                    except Exception:  # noqa: BLE001
                        hdb.rollback()
                        logger.warning(
                            "WhatsApp self-heal promote failed for %s:%s — disk healed from %s "
                            "but corrupt current persists in DB; will re-heal next boot",
                            tenant_id[:8], account_id, label,
                        )
                    finally:
                        hdb.close()
                return True

            # Every durable copy is unusable → the device is effectively gone
            # (a QR re-pair is the only honest outcome). Normalise on-disk state
            # so neonize starts from a deterministic clean slate — a pre-existing
            # torn .db from a prior SIGKILL-mid-write would otherwise be opened
            # by neonize. Safe here because every Postgres copy was already
            # proven unusable, so there is no good session to lose (review MTR-3).
            try:
                if os.path.exists(path):
                    os.replace(path, path + ".corrupt-backup")
            except Exception:  # noqa: BLE001
                logger.warning("WhatsApp restore: could not stash on-disk .corrupt-backup for %s", path)
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(path + suffix)
                except FileNotFoundError:
                    pass
                except Exception:  # noqa: BLE001
                    pass
            logger.error(
                "WhatsApp restore FAILED for %s:%s — all %d copies unusable; on-disk session "
                "cleared, device likely revoked, re-pair (QR) required",
                tenant_id[:8], account_id, len(candidates),
            )
            return False
        except Exception:
            logger.exception("Failed to restore WhatsApp session for %s:%s", tenant_id[:8], account_id)
            return False

    # ── Client lifecycle ─────────────────────────────────────────────

    def _create_client(self, tenant_id: str, account_id: str) -> NewAClient:
        """Create a neonize async client with event handlers bound."""
        key = self._key(tenant_id, account_id)
        name = self._client_name(tenant_id, account_id)

        # Always use SQLite for neonize session storage.
        # PostgreSQL URLs with special chars in password break Go's URL parser.
        client = NewAClient(name)

        # Fix event loop: neonize creates its own loop at import time
        # (asyncio.new_event_loop() that is never started), but we need
        # callbacks on the current running loop (uvicorn's). The execute()
        # method in neonize.aioze.events uses its own module-level
        # event_global_loop, so we must patch BOTH modules.
        try:
            loop = asyncio.get_running_loop()
            client.loop = loop
            import neonize.aioze.client as _neonize_client_mod
            import neonize.aioze.events as _neonize_events_mod
            _neonize_client_mod.event_global_loop = loop
            _neonize_events_mod.event_global_loop = loop
            logger.info(f"Patched neonize event loops for {key}")
        except RuntimeError:
            pass

        # QR callback
        @client.qr
        async def on_qr(c: NewAClient, data_qr: bytes):
            try:
                qr = segno.make_qr(data_qr.decode())
                buf = io.BytesIO()
                qr.save(buf, kind="png", scale=8)
                data_url = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"
                self._qr_codes[key] = data_url
                self._statuses[key] = "pairing"
                logger.info(f"QR code generated for {key}")
            except Exception:
                logger.exception(f"QR generation failed for {key}")

        # Pair status (fires on successful QR scan / phone linking)
        @client.event(PairStatusEv)
        async def on_pair_status(c: NewAClient, event: PairStatusEv):
            logger.info(f"Pair status event for {key}: {event}")
            # During a graceful drain the shutdown handler owns the teardown —
            # don't update status, save, or otherwise re-arm a writer (review C1).
            if self._draining:
                return
            self._statuses[key] = "connected"
            self._qr_codes.pop(key, None)
            phone = None
            try:
                me = await c.get_me()
                if me:
                    phone = me.User
            except Exception:
                pass
            self._update_account_status(tenant_id, account_id, "connected", phone=phone)
            self._log_event(tenant_id, account_id, "paired")
            self._save_session_to_db(tenant_id, account_id, source_event="pair")

        # Connected
        @client.event(ConnectedEv)
        async def on_connected(c: NewAClient, event: ConnectedEv):
            logger.info(f"ConnectedEv fired for {key}")
            # During a graceful drain, refuse to re-arm: no status flip, no
            # save, no heartbeat start (review C1). The drain set status to
            # logged_out and is tearing this client down.
            if self._draining:
                return
            self._statuses[key] = "connected"
            # 2026-05-20 fix: do NOT reset reconnect_counts here. The
            # previous version reset on every ConnectedEv, which let a
            # flapping connection restart at base delay every 2s and
            # hammer WhatsApp's server (verified in the 2026-05-19
            # incident logs). Counter resets via _delayed_counter_reset
            # only after STABLE_CONNECTION_SECONDS of continuous up.
            prev_reset = self._stable_reset_tasks.pop(key, None)
            if prev_reset and not prev_reset.done():
                prev_reset.cancel()
            self._stable_reset_tasks[key] = asyncio.ensure_future(
                self._delayed_counter_reset(key)
            )
            self._qr_codes.pop(key, None)
            phone = None
            try:
                me = await c.get_me()
                if me:
                    phone = me.User
            except Exception:
                pass
            self._update_account_status(tenant_id, account_id, "connected", phone=phone)
            self._log_event(tenant_id, account_id, "connection_opened")
            await self._save_session_locked(tenant_id, account_id, source_event="connected")
            self._start_heartbeat(tenant_id, account_id)
            # Register whatsapp shell in presence
            try:
                from app.services import luna_presence_service
                luna_presence_service.register_shell(tenant_id, "whatsapp")
            except Exception:
                pass

        # Disconnected — save session (keys may have rotated), then auto-reconnect
        @client.event(DisconnectedEv)
        async def on_disconnected(c: NewAClient, event: DisconnectedEv):
            logger.warning(f"DisconnectedEv for {key}")
            # Cancel the pending stable-counter-reset (if any) so the
            # next reconnect sees the escalated count, not zero.
            pending_reset = self._stable_reset_tasks.pop(key, None)
            if pending_reset and not pending_reset.done():
                pending_reset.cancel()
            # Cancel the heartbeat — a new one starts on next ConnectedEv.
            hb = self._heartbeat_tasks.pop(key, None)
            if hb and not hb.done():
                hb.cancel()
            await self._save_session_locked(tenant_id, account_id, source_event="disconnected")
            # During a graceful drain the shutdown handler owns the teardown
            # and has already set status=logged_out. Do NOT clobber it back to
            # "disconnected" or schedule an auto-reconnect — that would race the
            # drain's validated save and resurrect a live client mid-shutdown
            # (review C1-1). _draining short-circuits keep already-scheduled
            # reconnects inert too.
            if self._draining:
                self._log_event(tenant_id, account_id, "connection_closed")
                return
            self._statuses[key] = "disconnected"
            self._update_account_status(tenant_id, account_id, "disconnected")
            self._log_event(tenant_id, account_id, "connection_closed")
            # Mute presence while WhatsApp is disconnected
            try:
                from app.services import luna_presence_service
                luna_presence_service.update_state(tenant_id, privacy="muted")
            except Exception:
                pass
            # Schedule auto-reconnect
            asyncio.ensure_future(self._auto_reconnect(tenant_id, account_id))

        # NOTE: StreamReplacedEv is NOT registered — it crashes the neonize Go binary
        # with "panic: index out of range [0] with length 0" in CallbackFunction.
        # Disconnection is handled via DisconnectedEv instead.

        # Logged out
        @client.event(LoggedOutEv)
        async def on_logged_out(c: NewAClient, event: LoggedOutEv):
            logger.info(f"LoggedOutEv for {key}")
            self._statuses[key] = "logged_out"
            self._qr_codes.pop(key, None)
            self._update_account_status(tenant_id, account_id, "logged_out")
            self._log_event(tenant_id, account_id, "logged_out")
            # Mute presence when WhatsApp session ends
            try:
                from app.services import luna_presence_service
                luna_presence_service.update_state(tenant_id, privacy="muted")
            except Exception:
                pass

        # Inbound messages
        @client.event(MessageEv)
        async def on_message(c: NewAClient, event: MessageEv):
            try:
                await self._handle_inbound(key, tenant_id, account_id, c, event)
            except Exception:
                logger.exception(f"Error handling inbound message for {key}")

        self._clients[key] = client
        self._statuses[key] = "connecting"
        return client

    async def _auto_reconnect(self, tenant_id: str, account_id: str):
        """Auto-reconnect after disconnect with exponential backoff."""
        # Hard short-circuit during a graceful drain — a heartbeat/disconnect
        # callback may have scheduled us via a bare ensure_future the drain
        # can't cancel; refuse to re-arm a client mid-shutdown (review C1-1/C1-2).
        if self._draining:
            return
        key = self._key(tenant_id, account_id)
        attempt = self._reconnect_counts.get(key, 0) + 1
        self._reconnect_counts[key] = attempt

        if attempt > self.MAX_RECONNECT_ATTEMPTS:
            logger.error(f"Max reconnect attempts ({self.MAX_RECONNECT_ATTEMPTS}) reached for {key}")
            self._update_account_status(tenant_id, account_id, "disconnected",
                                        error=f"Max reconnect attempts reached after {attempt - 1} tries")
            return

        delay = self.RECONNECT_BASE_DELAY * (2 ** (attempt - 1))
        logger.info(f"Auto-reconnect attempt {attempt}/{self.MAX_RECONNECT_ATTEMPTS} for {key} in {delay}s")
        await asyncio.sleep(delay)

        # Check if status was manually changed (e.g., disabled, logged out)
        current_status = self._statuses.get(key)
        if current_status in ("logged_out", None):
            logger.info(f"Skipping auto-reconnect for {key} — status is {current_status}")
            return

        try:
            result = await self.reconnect(tenant_id, account_id)
            if result.get("status") == "unreachable":
                logger.warning(f"Auto-reconnect skipped for {key} — network unreachable, will retry")
                # Schedule another attempt (count already incremented)
                asyncio.ensure_future(self._auto_reconnect(tenant_id, account_id))
            else:
                logger.info(f"Auto-reconnect initiated for {key}")
        except Exception:
            logger.exception(f"Auto-reconnect failed for {key}")

    async def _connection_watchdog(self, key: str, tenant_id: str, account_id: str):
        """Monitor the connection task; reconnect if it dies unexpectedly."""
        try:
            task = self._tasks.get(key)
            if not task:
                return
            # Wait for the connection task to finish (it shouldn't under normal operation)
            await task
        except asyncio.CancelledError:
            return  # Normal shutdown
        except Exception as e:
            logger.warning(f"Connection task for {key} ended with error: {e}")

        # Connection task ended — check if we should reconnect
        status = self._statuses.get(key)
        if status in ("logged_out", None):
            return
        # If DisconnectedEv already triggered reconnect, skip
        if status == "connecting":
            return

        logger.warning(f"Connection task died for {key} (status={status}), triggering auto-reconnect")
        self._statuses[key] = "disconnected"
        self._update_account_status(tenant_id, account_id, "disconnected")
        await self._auto_reconnect(tenant_id, account_id)

    async def _handle_inbound(
        self, key: str, tenant_id: str, account_id: str,
        client: NewAClient, event: MessageEv,
    ):
        """Process an inbound WhatsApp message through agent pipeline."""
        # Drain gate at the true inbound entrypoint (review C1-4): refuse new
        # work BEFORE the up-to-90s media download / transcription, not just at
        # the chat-turn boundary, so a draining instance doesn't start expensive
        # ingest it will then drop.
        if self._draining:
            logger.info("WhatsApp draining — dropping inbound message for %s", key)
            return
        info = event.Info
        msg = event.Message

        sender_jid_obj = info.MessageSource.Sender  # Full JID object (preserves LID vs phone)
        sender_jid = sender_jid_obj.User if sender_jid_obj else ""
        chat_jid = info.MessageSource.Chat.User if info.MessageSource.Chat else ""
        is_from_me = info.MessageSource.IsFromMe
        is_group = info.MessageSource.IsGroup
        text = msg.conversation or (msg.extendedTextMessage.text if msg.extendedTextMessage else "")

        # Extract message ID for echo detection
        msg_id = info.ID if hasattr(info, 'ID') else ""

        # Detect media messages (images, audio, documents)
        media_bytes = None
        media_mime = None
        media_type = None
        media_caption = text

        media_type, media_mime, media_caption = _detect_inbound_media(msg, text)

        # Download media if present
        # Audio can be large — use a longer timeout than images/docs
        if media_type:
            _download_timeout = 90 if media_type == "audio" else 30
            try:
                media_bytes = await asyncio.wait_for(
                    client.download_any(event.Message), timeout=_download_timeout,
                )
                logger.info(f"Downloaded {media_type} ({len(media_bytes)} bytes) from {sender_jid}")
            except Exception as e:
                # Audio-specific neonize regression 2026-05-24: download_any
                # raises "didn't find any attachments in message" for inbound
                # AudioMessage despite the audioMessage being present in the
                # envelope. Text and image downloads via download_any continue
                # to work. Fall back to download_media_with_path called
                # directly with the audio fields — bypasses the broken
                # attachment-detection branch on the Go side while keeping
                # everything else unchanged.
                _err_str = str(e)
                _audio_attachment_miss = (
                    media_type == "audio"
                    and "didn't find any attachments" in _err_str
                )
                if _audio_attachment_miss:
                    try:
                        from neonize.utils.enum import (
                            MediaType as _MediaType,
                            MediaTypeToMMS as _MediaTypeToMMS,
                        )
                        audio_msg = getattr(msg, "audioMessage", None)
                        if audio_msg is None:
                            raise RuntimeError(
                                "audioMessage missing on fallback path "
                                "(should have been present per _detect_inbound_media)"
                            )
                        media_bytes = await asyncio.wait_for(
                            client.download_media_with_path(
                                audio_msg.directPath,
                                audio_msg.fileEncSHA256,
                                audio_msg.fileSHA256,
                                audio_msg.mediaKey,
                                audio_msg.fileLength,
                                _MediaType.MediaAudio,
                                _MediaTypeToMMS.MediaAudio,
                            ),
                            timeout=_download_timeout,
                        )
                        logger.info(
                            "Downloaded audio (%d bytes) via "
                            "download_media_with_path fallback for %s — "
                            "neonize download_any attachment-detection "
                            "workaround",
                            len(media_bytes), sender_jid,
                        )
                    except Exception as fallback_exc:
                        logger.warning(
                            "Audio fallback download_media_with_path also "
                            "failed for %s: %s (original error: %s)",
                            sender_jid, fallback_exc, e,
                        )
                        media_bytes = None
                else:
                    logger.warning(
                        f"Failed to download {media_type} from {sender_jid}: {e}"
                    )
                    media_bytes = None

        # Skip if no text AND no media
        if not text and not media_bytes and not media_type:
            return

        # Skip group messages — only handle DMs for now
        if is_group:
            return

        # Skip messages the user sends to other contacts — only process self-chat or inbound DMs
        if is_from_me and chat_jid != sender_jid:
            return

        # Skip bot echo replies in self-chat
        if is_from_me:
            sent_ids = self._sent_message_ids.get(key, set())
            if msg_id and msg_id in sent_ids:
                sent_ids.discard(msg_id)
                return

        # Resolve LID → phone number if needed (WhatsApp now uses LIDs for DMs)
        sender_phone = sender_jid  # default: assume JID is the phone
        try:
            # neonize client method to resolve LID to phone number
            pn_result = await asyncio.wait_for(client.get_pn_from_lid(sender_jid_obj), timeout=5)
            if pn_result:
                resolved = pn_result.User if hasattr(pn_result, 'User') else str(pn_result)
                logger.info(f"Resolved LID {sender_jid} → phone {resolved}")
                sender_phone = resolved
                self._lid_phone_cache[sender_jid] = resolved
        except Exception as e:
            logger.debug(f"LID→phone resolution failed for {sender_jid}: {e}")
            # Fallback 1: check LID→phone cache from previous successful resolutions
            if sender_jid in self._lid_phone_cache:
                sender_phone = self._lid_phone_cache[sender_jid]
                logger.info(f"Using cached LID→phone: {sender_jid} → {sender_phone}")
            # Fallback 2: in DMs, chat_jid is often the phone number even when sender is a LID
            elif not is_group and chat_jid and chat_jid != sender_jid:
                sender_phone = chat_jid
                logger.info(f"Using chat JID as phone fallback: {sender_jid} → {chat_jid}")

        # DM policy enforcement
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            if acct.dm_policy == "allowlist":
                allowed = acct.allow_from or []
                if "*" not in allowed:
                    allowed_variants = set()
                    for allowed_value in allowed:
                        allowed_variants.update(_phone_variants(allowed_value))

                    candidates = set()
                    candidates.update(_phone_variants(sender_jid))
                    candidates.update(_phone_variants(sender_phone))
                    candidates.update(_phone_variants(chat_jid))

                    matches = bool(candidates & allowed_variants)
                    if not matches:
                        logger.info(f"Blocked message from {sender_jid} (phone={sender_phone}, not in allowlist {allowed})")
                        return
        finally:
            db.close()

        # Update presence: listening on whatsapp
        try:
            from app.services import luna_presence_service
            luna_presence_service.update_state(tenant_id, state="listening", active_shell="whatsapp")
        except Exception:
            pass

        logger.info(f"Inbound DM from {sender_phone} (jid={sender_jid}) in {key}: {text[:100]}")
        self._log_event(
            tenant_id, account_id, "message_inbound",
            direction="inbound", remote_id=sender_phone,
            message_content=text,
            extra_data={"chat_jid": chat_jid, "is_group": is_group},
        )

        # Typing ("composing") presence + the reply send are now owned by the
        # per-sender chat consumer (_run_turn). This handler only does media
        # prep, builds the turn, and enqueues it — it never blocks on the CLI
        # run, so a slow/hung turn can't starve other WhatsApp messages (the
        # thread-pool wedge of 2026-06-04). reply_jid is captured here and
        # carried on the turn.
        reply_jid = build_jid(sender_phone)

        # Process through agent — use phone number (not LID) as session key
        try:
            media_parts = None
            doc_text = None

            if media_bytes and media_type == "document":
                # Documents (PDF, Excel, CSV, text): extract text locally, embed it.
                # Don't send raw bytes to the LLM — process in Python.
                media_filename = ""
                if msg.documentMessage:
                    media_filename = msg.documentMessage.fileName or msg.documentMessage.title or ""
                doc_text = await self._extract_and_embed_document(
                    tenant_id, media_bytes, media_mime or "", media_filename,
                )
            elif media_bytes and media_type == "image":
                # Images: save locally, embed, and describe for CLI agents
                # CLI mode can't process inline images — extract description
                import base64
                img_b64 = base64.b64encode(media_bytes).decode()
                img_size = len(media_bytes)
                doc_text = (
                    f"[User sent an image ({media_mime or 'image'}, {img_size:,} bytes). "
                    f"Caption: {media_caption or 'no caption'}. "
                    f"Please acknowledge the image was received and respond based on the caption/context.]"
                )
                # Also build media_parts for multimodal processing
                try:
                    from app.services.media_utils import build_media_parts
                    media_parts, _ = build_media_parts(
                        media_bytes=media_bytes,
                        mime_type=media_mime,
                        caption=media_caption or "",
                        filename="",
                    )
                except ValueError:
                    pass
                # Embed image description for future recall
                try:
                    from app.services.embedding_service import embed_and_store
                    from app.db.session import SessionLocal
                    import uuid as _uuid
                    edb = SessionLocal()
                    try:
                        embed_and_store(
                            edb,
                            tenant_id=_uuid.UUID(tenant_id),
                            content_type="whatsapp_image",
                            content_id=f"wa_img_{hash(media_bytes) % 10000}",
                            text_content=f"Image from {sender_phone}: {media_caption or 'no caption'}",
                        )
                        edb.commit()
                    finally:
                        edb.close()
                except Exception:
                    pass
            elif media_bytes and media_type == "audio":
                # Audio (voice notes): transcribe via the code-worker
                # workflow. _handle_inbound is async, so we MUST go through
                # transcribe_async — transcribe_bytes_sync's ThreadPoolExecutor
                # bridge blocks the event loop. See transcription_client.py.
                try:
                    from app.services.transcription_client import (
                        TranscriptionUnavailable,
                        transcribe_async,
                    )
                    transcript = None
                    try:
                        tr = await transcribe_async(
                            media_bytes,
                            sync_timeout=WHATSAPP_AUDIO_TRANSCRIBE_TIMEOUT_SECONDS,
                        )
                        if tr.status == "completed":
                            transcript = tr.transcript
                        elif tr.status == "pending":
                            logger.warning(
                                "WhatsApp audio transcription still pending after %.0fs "
                                "for %s (job=%s)",
                                WHATSAPP_AUDIO_TRANSCRIBE_TIMEOUT_SECONDS,
                                sender_phone,
                                tr.job_id,
                            )
                    except TranscriptionUnavailable as exc:
                        logger.warning(
                            f"Transcription unavailable for {sender_phone}: {exc}"
                        )
                    if transcript:
                        logger.info(f"Whisper transcript ({len(transcript)} chars) for {sender_phone}")
                        doc_text = transcript
                    else:
                        logger.warning(
                            "WhatsApp audio transcription empty for %s; "
                            "CLI channel cannot consume inline audio",
                            sender_phone,
                        )
                except Exception as e:
                    logger.warning(f"Audio processing failed for {sender_phone}: {e}")
            elif media_bytes:
                # Other media types: send to LLM as media_parts
                try:
                    from app.services.media_utils import build_media_parts
                    media_parts, _ = build_media_parts(
                        media_bytes=media_bytes,
                        mime_type=media_mime,
                        caption=media_caption or "",
                        filename="",
                    )
                except ValueError as e:
                    logger.warning(f"Media processing failed for {sender_phone}: {e}")

            # If we extracted document/audio text, prepend it to the agent message
            if doc_text:
                if media_type == "audio":
                    # Voice note — send transcript directly, no document wrapper
                    agent_text = doc_text
                else:
                    media_filename = ""
                    if msg.documentMessage:
                        media_filename = msg.documentMessage.fileName or msg.documentMessage.title or ""
                    agent_text = f"[User sent document: {media_filename}]\n\nExtracted content:\n{doc_text[:3000]}"
                    if len(doc_text) > 3000:
                        agent_text += f"\n\n(Document truncated — {len(doc_text)} chars total, embedded for search)"
            elif media_type == "audio":
                agent_text = WHATSAPP_AUDIO_TRANSCRIPTION_FALLBACK
            else:
                agent_text = media_caption or text or f"[Sent {media_type}]"

            # Fire-and-forget: build the turn (resolve session + create a
            # chat_job) and enqueue it on its per-sender ordered queue. The
            # consumer runs the CLI turn on the dedicated WhatsApp executor,
            # keeps "typing…" alive, and sends the reply (or a fallback) when
            # it finishes — this handler returns now and never blocks on the
            # multi-minute run.
            turn = await self._build_turn(
                tenant_id, account_id, sender_phone, reply_jid,
                agent_text, media_parts, key,
            )
            if turn is not None:
                await self._enqueue_turn(turn)
        except Exception:
            logger.exception(
                "Failed to enqueue WhatsApp turn for %s (jid=%s)", sender_phone, sender_jid,
            )

    async def _extract_and_embed_document(
        self, tenant_id: str, media_bytes: bytes, mime_type: str, filename: str,
    ) -> Optional[str]:
        """Extract text from a document and embed it locally. No LLM needed.

        Supports PDF, Excel, CSV, and plain text files.
        Returns extracted text or None on failure.
        """
        import io
        text_content = None

        try:
            # PDF
            if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
                import pdfplumber
                with pdfplumber.open(io.BytesIO(media_bytes)) as pdf:
                    pages = [p.extract_text() for p in pdf.pages if p.extract_text()]
                    text_content = "\n\n".join(pages) if pages else None

            # Excel
            elif "spreadsheet" in mime_type or "excel" in mime_type or filename.lower().endswith((".xlsx", ".xls")):
                import pandas as pd
                df = pd.read_excel(io.BytesIO(media_bytes))
                text_content = df.to_string(max_rows=200)

            # CSV
            elif "csv" in mime_type or filename.lower().endswith(".csv"):
                text_content = media_bytes.decode("utf-8", errors="replace")

            # Plain text / code
            elif mime_type.startswith("text/") or filename.lower().endswith((".txt", ".md", ".json", ".py", ".js")):
                text_content = media_bytes.decode("utf-8", errors="replace")

            if not text_content:
                return None

            logger.info(f"Extracted {len(text_content)} chars from {filename} ({mime_type})")

            # Embed the document content for semantic search
            try:
                from app.services.embedding_service import embed_and_store
                from app.db.session import SessionLocal
                import uuid as _uuid
                db = SessionLocal()
                try:
                    embed_and_store(
                        db,
                        tenant_id=_uuid.UUID(tenant_id),
                        content_type="whatsapp_document",
                        content_id=f"wa_{filename}_{hash(media_bytes) % 10000}",
                        text_content=text_content[:8000],
                    )
                    db.commit()
                    logger.info(f"Embedded document {filename} for tenant {tenant_id[:8]}")
                finally:
                    db.close()
            except Exception:
                logger.debug("Document embedding failed (non-fatal)", exc_info=True)

            return text_content

        except Exception:
            logger.warning(f"Document extraction failed for {filename}", exc_info=True)
            return None

    async def _build_turn(
        self, tenant_id: str, account_id: str, sender_id: str, reply_jid,
        message: str, media_parts: list | None, account_key: str,
    ) -> "Optional[_WaChatTurn]":
        """Resolve the WhatsApp chat session + agent and create a queued
        chat_job, returning a ready-to-enqueue turn. Fast synchronous DB work
        only — NO CLI run here (that happens later on the dedicated executor).

        Returns None when draining or when the tenant has no user/agent. This
        replaces the old blocking ``_process_through_agent``: the multi-minute
        CLI run no longer holds the inbound handler's thread (the thread-pool
        wedge of 2026-06-04).
        """
        # Drain gate: once shutdown has begun, do not start a new chat turn.
        if self._draining:
            logger.info("WhatsApp draining — refusing new chat turn for %s", sender_id)
            return None
        db = self._get_db()
        try:
            from app.services import chat_jobs as chat_jobs_service
            from app.models.agent import Agent
            from app.services._agent_ordering import agent_status_rank
            from app.models.user import User

            tid = uuid.UUID(tenant_id)

            user = db.query(User).filter(User.tenant_id == tid).first()
            if not user:
                logger.error(f"No user found for tenant {tenant_id}")
                return None

            # Primary agent — prefer Luna, then production > staging > draft.
            agent = (
                db.query(Agent)
                .filter(Agent.tenant_id == tid)
                .order_by(
                    (Agent.name == "Luna").desc(),
                    agent_status_rank.asc(),
                    Agent.id.asc(),
                )
                .first()
            )
            if not agent:
                logger.warning(f"No agent found for tenant {tenant_id}")
                return None

            session_key = f"whatsapp:{sender_id}"
            session = (
                db.query(ChatSession)
                .filter(
                    ChatSession.tenant_id == tid,
                    ChatSession.source == "whatsapp",
                    ChatSession.external_id == session_key,
                )
                .first()
            )
            if not session:
                session = ChatSession(
                    title=f"WhatsApp: {sender_id}",
                    tenant_id=tid,
                    agent_id=agent.id,
                    source="whatsapp",
                    external_id=session_key,
                )
                db.add(session)
                db.commit()
                db.refresh(session)
            elif not session.agent_id:
                session.agent_id = agent.id
                db.commit()
                db.refresh(session)

            job = chat_jobs_service.create_job(
                db,
                session_id=session.id,
                tenant_id=tid,
                user_id=user.id,
                content=message,
            )
            logger.info(
                "[chat-trace] enqueue: job=%s session=%s sender=%s",
                job["id"][:8], str(session.id)[:8], sender_id,
            )
            return _WaChatTurn(
                queue_key=f"{account_key}::{sender_id}",
                account_key=account_key,
                tenant_id=tid,
                tenant_id_str=tenant_id,
                account_id=account_id,
                sender_phone=sender_id,
                reply_jid=reply_jid,
                job_uuid=uuid.UUID(job["id"]),
                session_id=session.id,
                user_id=user.id,
                content=message,
                media_parts=media_parts,
            )
        except Exception:
            logger.exception("Failed to build WhatsApp chat turn")
            db.rollback()
            return None
        finally:
            db.close()

    async def _enqueue_turn(self, turn: "_WaChatTurn") -> None:
        """Capacity-gated enqueue onto the per-sender ordered queue; spawns the
        consumer if needed. Over-cap (global OR per-sender) → terminalize the
        job + overloaded fallback, never an unbounded in-memory pile-up."""
        accepted = False
        async with self._chat_dispatch_lock:
            q = self._chat_queues.get(turn.queue_key)
            pending = q.qsize() if q is not None else 0
            if (self._chat_inflight_global < WHATSAPP_CHAT_GLOBAL_CAP
                    and pending < WHATSAPP_CHAT_PER_SENDER_CAP):
                if q is None:
                    q = asyncio.Queue()
                    self._chat_queues[turn.queue_key] = q
                q.put_nowait(turn)
                self._chat_inflight_global += 1
                consumer = self._chat_consumers.get(turn.queue_key)
                if consumer is None or consumer.done():
                    self._chat_consumers[turn.queue_key] = asyncio.create_task(
                        self._chat_consumer(turn.queue_key)
                    )
                accepted = True
        if not accepted:
            logger.warning(
                "WhatsApp chat over capacity (global=%d, sender=%s) — rejecting turn",
                self._chat_inflight_global, turn.sender_phone,
            )
            self._fail_job_safe(turn, "over capacity")
            await self._send_text(turn.account_key, turn.reply_jid, WHATSAPP_OVERLOADED_FALLBACK)

    async def _chat_consumer(self, queue_key: str) -> None:
        """One consumer per ordering key — drains its queue strictly
        sequentially so a sender's turns (and replies) stay ordered, then GCs
        itself when the queue empties (respawning if a turn raced teardown)."""
        q = self._chat_queues.get(queue_key)
        if q is None:
            return
        try:
            while True:
                try:
                    turn = q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    await self._run_turn(turn)
                finally:
                    async with self._chat_dispatch_lock:
                        self._chat_inflight_global = max(0, self._chat_inflight_global - 1)
                    q.task_done()
        finally:
            # GC under the lock; respawn if a turn arrived during teardown so
            # no enqueue is silently dropped — but never during drain (the loop
            # may be closing) and never crash if create_task can't run.
            async with self._chat_dispatch_lock:
                if self._chat_queues.get(queue_key) is q and (q.empty() or self._draining):
                    self._chat_queues.pop(queue_key, None)
                    self._chat_consumers.pop(queue_key, None)
                elif self._chat_queues.get(queue_key) is q and not self._draining:
                    try:
                        self._chat_consumers[queue_key] = asyncio.create_task(
                            self._chat_consumer(queue_key)
                        )
                    except RuntimeError:
                        self._chat_consumers.pop(queue_key, None)

    async def _run_turn(self, turn: "_WaChatTurn") -> None:
        """Run ONE turn: keep typing alive, execute run_job_blocking on the
        dedicated executor (backstop-bounded by WHATSAPP_JOB_WATCH_TIMEOUT),
        then send the reply or a fallback. Brackets _inflight_turns + records
        the active turn so drain can wait for / notify it."""
        import functools
        from app.services import chat_jobs as chat_jobs_service

        typing_done = asyncio.Event()
        typing_task = asyncio.create_task(
            self._keep_typing(turn.account_key, turn.reply_jid, typing_done)
        )
        self._inflight_turns += 1
        self._chat_active[turn.queue_key] = turn
        try:
            loop = asyncio.get_running_loop()
            try:
                fut = loop.run_in_executor(
                    self._chat_executor,
                    functools.partial(
                        chat_jobs_service.run_job_blocking,
                        turn.job_uuid,
                        session_id=turn.session_id,
                        tenant_id=turn.tenant_id,
                        user_id=turn.user_id,
                        content=turn.content,
                        media_parts=turn.media_parts,
                        sender_phone=turn.sender_phone,
                    ),
                )
            except RuntimeError:
                # Executor already shut down (drain in progress) — terminalize
                # + fallback rather than leaving the job 'queued' (Luna R5).
                logger.warning("WhatsApp executor unavailable — failing job=%s", turn.job_uuid)
                self._fail_job_safe(turn, "executor unavailable")
                await self._send_reply_or_fallback(turn, None, False)
                return
            try:
                await asyncio.wait_for(fut, timeout=WHATSAPP_JOB_WATCH_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning(
                    "WhatsApp turn watch timed out (%.0fs) for job=%s — sending fallback",
                    WHATSAPP_JOB_WATCH_TIMEOUT, turn.job_uuid,
                )
            reply, ok = self._read_job_reply(turn)
            await self._send_reply_or_fallback(turn, reply, ok)
        except Exception:
            logger.exception("WhatsApp turn failed for job=%s", turn.job_uuid)
            try:
                await self._send_reply_or_fallback(turn, None, False)
            except Exception:
                logger.exception("WhatsApp fallback send failed for job=%s", turn.job_uuid)
        finally:
            self._chat_active.pop(turn.queue_key, None)
            typing_done.set()
            try:
                await typing_task
            except Exception:
                pass
            self._inflight_turns -= 1

    async def _keep_typing(self, account_key: str, reply_jid, typing_done: asyncio.Event) -> None:
        """Refresh COMPOSING presence every 4s until ``typing_done``. Re-reads
        the client each loop so a mid-turn reconnect doesn't strand it."""
        while not typing_done.is_set():
            client = self._clients.get(account_key)
            if client is not None:
                try:
                    await client.send_chat_presence(
                        reply_jid,
                        ChatPresence.CHAT_PRESENCE_COMPOSING,
                        ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
                    )
                except Exception:
                    pass
            try:
                await asyncio.wait_for(typing_done.wait(), timeout=4.0)
                break
            except asyncio.TimeoutError:
                continue

    def _read_job_reply(self, turn: "_WaChatTurn") -> "tuple[Optional[str], bool]":
        """Read the terminal job → (reply_text, ok). ok=True only on status
        'done' with non-empty concatenated chunk text."""
        from app.services import chat_jobs as chat_jobs_service
        db = self._get_db()
        try:
            job = chat_jobs_service.get_job(db, job_id=turn.job_uuid, tenant_id=turn.tenant_id)
            if not job:
                return None, False
            if job["status"] != "done":
                logger.info(
                    "WhatsApp job=%s terminal status=%s — fallback",
                    str(turn.job_uuid)[:8], job["status"],
                )
                return None, False
            txt = chat_jobs_service.reply_text_from_events(db, job_id=turn.job_uuid)
            return (txt or None), bool(txt)
        except Exception:
            logger.exception("WhatsApp read_job_reply failed for job=%s", turn.job_uuid)
            return None, False
        finally:
            db.close()

    async def _send_reply_or_fallback(
        self, turn: "_WaChatTurn", reply: Optional[str], ok: bool
    ) -> None:
        """Send the reply (chunked at 4000) on success, else a fallback.
        Re-reads the client at send time (reconnect-safe), tracks sent IDs for
        echo suppression, logs the outbound event, and sets PAUSED presence."""
        client = self._clients.get(turn.account_key)
        if client is None:
            logger.warning(
                "WhatsApp send: no client for %s — dropping reply for job=%s",
                turn.account_key, turn.job_uuid,
            )
            return
        if ok and reply:
            try:
                chunks = [reply] if len(reply) <= 4000 else [
                    reply[i:i + 4000] for i in range(0, len(reply), 4000)
                ]
                for chunk in chunks:
                    resp = await client.send_message(turn.reply_jid, chunk)
                    if resp and getattr(resp, "ID", None):
                        sent_ids = self._sent_message_ids.setdefault(turn.account_key, set())
                        sent_ids.add(resp.ID)
                        if len(sent_ids) > 100:
                            sent_ids.pop()
                self._log_event(
                    turn.tenant_id_str, turn.account_id, "message_outbound",
                    direction="outbound", remote_id=turn.sender_phone,
                    message_content=reply,
                )
                try:
                    await client.send_chat_presence(
                        turn.reply_jid,
                        ChatPresence.CHAT_PRESENCE_PAUSED,
                        ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
                    )
                except Exception:
                    pass
            except Exception:
                logger.exception(
                    "WhatsApp send failed for %s (job=%s)", turn.sender_phone, turn.job_uuid,
                )
        else:
            try:
                await client.send_message(turn.reply_jid, WHATSAPP_TURN_FAILED_FALLBACK)
            except Exception:
                logger.exception(
                    "WhatsApp fallback send failed for %s (job=%s)",
                    turn.sender_phone, turn.job_uuid,
                )

    async def _send_text(self, account_key: str, reply_jid, text: str) -> None:
        """Best-effort single text send (capacity / restart notices)."""
        client = self._clients.get(account_key)
        if client is None:
            return
        try:
            await client.send_message(reply_jid, text)
        except Exception:
            logger.exception("WhatsApp _send_text failed for %s", account_key)

    def _fail_job_safe(self, turn: "_WaChatTurn", error: str) -> None:
        """Terminalize a created-but-not-run job (over-cap / submit failure) so
        it can't linger as 'queued'. fail_job's NOT-IN-terminal guard covers
        the queued→failed flip directly."""
        from app.services import chat_jobs as chat_jobs_service
        db = self._get_db()
        try:
            chat_jobs_service.fail_job(db, job_id=turn.job_uuid, error=error)
        except Exception:
            logger.exception("WhatsApp _fail_job_safe failed for job=%s", turn.job_uuid)
        finally:
            db.close()

    async def _drain_chat_consumers(self) -> None:
        """Shutdown: best-effort 'restarting' notice to every sender with a
        pending or mid-flight turn, cancel all consumers, stop the executor."""
        async with self._chat_dispatch_lock:
            queues = list(self._chat_queues.items())
            consumers = list(self._chat_consumers.values())
            active = list(self._chat_active.values())
            self._chat_queues.clear()
            self._chat_consumers.clear()
        notify: list[_WaChatTurn] = list(active)
        for _qk, q in queues:
            while True:
                try:
                    notify.append(q.get_nowait())
                except Exception:
                    break
        notified: set = set()
        for turn in notify:
            if turn.queue_key in notified:
                continue
            notified.add(turn.queue_key)
            try:
                await self._send_text(turn.account_key, turn.reply_jid, WHATSAPP_RESTART_FALLBACK)
            except Exception:
                pass
        for task in consumers:
            if task and not task.done():
                task.cancel()
        try:
            self._chat_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    # ── Public API ───────────────────────────────────────────────────

    async def enable(
        self, tenant_id: str, account_id: str = "default",
        dm_policy: str = "allowlist", allow_from: list = None,
    ) -> dict:
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            acct.enabled = True
            acct.dm_policy = dm_policy
            acct.allow_from = allow_from or []
            acct.updated_at = datetime.utcnow()
            db.commit()
            return {"account_id": account_id, "enabled": True, "dm_policy": dm_policy}
        finally:
            db.close()

    async def disable(self, tenant_id: str, account_id: str = "default") -> dict:
        key = self._key(tenant_id, account_id)
        # Prevent auto-reconnect
        self._statuses[key] = "logged_out"
        # Cancel watchdog + heartbeat
        watchdog = self._watchdog_tasks.pop(key, None)
        if watchdog and not watchdog.done():
            watchdog.cancel()
        hb = self._heartbeat_tasks.pop(key, None)
        if hb and not hb.done():
            hb.cancel()
        # Disconnect if active
        if key in self._clients:
            try:
                await self._clients[key].disconnect()
            except Exception:
                pass
            self._clients.pop(key, None)
            self._qr_codes.pop(key, None)
        # Cancel background task
        task = self._tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

        # Purge the on-disk neonize SQLite session file. Without this,
        # the next `start_pairing` rehydrates the existing device
        # credentials and never shows a QR — diagnosed 2026-05-20 with
        # Simon (4 incidents in one session). See
        # whatsapp_sqlite_corruption_recovery.md + Luna observation
        # 3d01949b.
        self._purge_local_session_file(tenant_id, account_id, reason="disable")

        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            acct.enabled = False
            acct.status = "disconnected"
            acct.updated_at = datetime.utcnow()
            db.commit()
            return {"account_id": account_id, "enabled": False}
        finally:
            db.close()

    async def update_settings(
        self, tenant_id: str, account_id: str = "default",
        dm_policy: str = "allowlist", allow_from: list = None,
    ) -> dict:
        """Update allowlist / DM policy without changing enabled state."""
        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            acct.dm_policy = dm_policy
            acct.allow_from = allow_from or []
            acct.updated_at = datetime.utcnow()
            db.commit()
            return {"account_id": account_id, "dm_policy": dm_policy, "allow_from": acct.allow_from}
        finally:
            db.close()

    async def start_pairing(
        self, tenant_id: str, account_id: str = "default", force: bool = False,
    ) -> dict:
        key = self._key(tenant_id, account_id)

        # force=True is the ONLY legitimate destructive path: it tears down
        # the device session so neonize mints a FRESH QR. It is reserved for
        # an explicit OPERATOR unlink / re-pair — recovery code (reconnect /
        # restore_connections / heartbeat / _auto_reconnect) must NEVER reach
        # here (design §6, Codex-5.5 review #5).
        if force:
            # Disconnect OUTSIDE the session lock: client.disconnect() dispatches
            # the on_disconnected handler, which acquires this same lock via
            # _save_session_locked — holding the lock across disconnect could
            # self-deadlock (review FG-1, the same hazard the drain handler
            # avoids). A late on_disconnected save can't resurrect the device:
            # we delete the on-disk file under the lock below, and
            # _save_session_to_db no-ops when the file is gone.
            if key in self._clients:
                try:
                    await self._clients[key].disconnect()
                except Exception:
                    pass
                self._clients.pop(key, None)
            task = self._tasks.pop(key, None)
            if task and not task.done():
                task.cancel()
            # The destructive file + DB teardown is serialized under the session
            # lock so it can't race a concurrent _save_session_to_db that would
            # re-persist stale auth right after we cleared it (CRITICAL RACE #1).
            async with self._get_session_lock(key):
                self._qr_codes.pop(key, None)
                session_path = self._client_name(tenant_id, account_id)
                # Keep a single rolling forensic copy of the .db before
                # deleting (overwrites any prior .corrupt-backup).
                try:
                    if os.path.exists(session_path):
                        os.replace(session_path, session_path + ".corrupt-backup")
                except Exception:  # noqa: BLE001
                    logger.warning("force re-pair: could not stash .corrupt-backup for %s", session_path)
                for suffix in ("", "-wal", "-shm"):
                    try:
                        os.remove(session_path + suffix)
                    except FileNotFoundError:
                        pass
                # Clear the current blob AND the rolling backups — a real
                # re-pair must not let restore_connections resurrect the old
                # device from a backup tier on the next boot.
                db = self._get_db()
                try:
                    acct = self._get_or_create_account(db, tenant_id, account_id)
                    acct.session_blob = None
                    acct.status = "pairing"
                    deleted = (
                        db.query(WhatsappSessionBackup)
                        .filter(
                            WhatsappSessionBackup.tenant_id == acct.tenant_id,
                            WhatsappSessionBackup.account_id == account_id,
                        )
                        .delete()
                    )
                    db.commit()
                    logger.warning(
                        "Operator force re-pair for %s:%s — cleared current session + %d backup(s); minting fresh QR",
                        tenant_id[:8], account_id, deleted,
                    )
                except Exception:
                    db.rollback()
                finally:
                    db.close()

        # Pre-flight: verify WhatsApp is reachable before connect() —
        # neonize Go code panics (kills process) on TLS handshake timeout.
        reachable = await asyncio.get_event_loop().run_in_executor(
            None, self._is_whatsapp_reachable, self.WHATSAPP_CONNECT_TIMEOUT
        )
        if not reachable:
            logger.warning(f"WhatsApp unreachable, cannot start pairing for {key}")
            self._statuses[key] = "disconnected"
            self._update_account_status(tenant_id, account_id, "disconnected",
                                        error="WhatsApp servers unreachable")
            return {"error": "WhatsApp servers are currently unreachable. Check network connectivity."}

        # Create client and start connection (QR will be emitted via callback)
        client = self._create_client(tenant_id, account_id)
        self._clients[key] = client
        # Reset reconnect counter on fresh pairing
        self._reconnect_counts[key] = 0
        # connect() returns a Task — await to get the actual running connection task
        connect_task = await client.connect()
        self._tasks[key] = connect_task
        # Start watchdog to detect unexpected disconnects (StreamReplaced, EOF, etc.)
        old_watchdog = self._watchdog_tasks.pop(key, None)
        if old_watchdog and not old_watchdog.done():
            old_watchdog.cancel()
        self._watchdog_tasks[key] = asyncio.ensure_future(
            self._connection_watchdog(key, tenant_id, account_id)
        )

        # Wait briefly for QR to be generated or existing session to restore
        for i in range(30):
            await asyncio.sleep(0.5)
            if key in self._qr_codes:
                return {
                    "qr_data_url": self._qr_codes[key],
                    "message": "Scan QR code with WhatsApp > Linked Devices > Link a Device",
                }
            if self._statuses.get(key) == "connected":
                return {
                    "qr_data_url": None,
                    "message": "Already connected (existing session restored)",
                    "connected": True,
                }
            # After 3 seconds, also check active connection (session may auto-restore
            # without events firing after whatsmeow's internal 515 reconnect).
            if i >= 6:
                try:
                    # Sync .connected attr is most reliable indicator of active connection
                    connected = getattr(client, "connected", False)
                    # Fallback: check if we have credentials on disk
                    logged_in = False
                    try:
                        # is_logged_in is a PROPERTY on neonize NewAClient
                        # (verified 2026-05-20). Drop the parens; the getter
                        # may return either a bool or an awaitable
                        # depending on the build. Same fix pattern as
                        # _socket_heartbeat in PR #599.
                        res = client.is_logged_in
                        if inspect.isawaitable(res):
                            logged_in = await asyncio.wait_for(res, timeout=2)
                        else:
                            logged_in = bool(res)
                    except Exception as e:
                        logger.debug(f"is_logged_in check failed: {e}")
                        pass
                        
                    logger.info(f"start_pairing: active probe i={i} connected={connected} logged_in={logged_in} for {key}")
                    
                    if connected:
                        phone = None
                        try:
                            me = await asyncio.wait_for(client.get_me(), timeout=3)
                            phone = me.User if me else None
                        except Exception:
                            pass
                        logger.info(f"start_pairing: active detection found {key} connected as {phone}")
                        self._statuses[key] = "connected"
                        self._qr_codes.pop(key, None)
                        self._update_account_status(tenant_id, account_id, "connected", phone=phone)
                        self._save_session_to_db(tenant_id, account_id, source_event="connected")
                        return {
                            "qr_data_url": None,
                            "message": "Already connected (existing session restored)",
                            "connected": True,
                        }
                    elif logged_in:
                        # Authenticated but not yet connected to servers (maybe 515 reconnecting)
                        # We stay in the loop to wait for real connection or QR
                        self._statuses[key] = "connecting"
                        self._qr_codes.pop(key, None)
                        
                except Exception as e:
                    logger.info(f"start_pairing: active probe error: {e}")

        return {
            "qr_data_url": None,
            "message": "QR code not yet available, try polling /pair/status",
        }

    async def get_pairing_status(self, tenant_id: str, account_id: str = "default") -> dict:
        key = self._key(tenant_id, account_id)
        status = self._statuses.get(key, "disconnected")

        # Active detection: if status isn't "connected" yet, check if the
        # client is actually authenticated (event callbacks may not fire after
        # whatsmeow's internal 515 reconnect during pairing).
        if status != "connected" and key in self._clients:
            client = self._clients[key]
            try:
                # Check sync .connected attr first
                connected = getattr(client, "connected", False)
                
                # Check logged_in as fallback
                logged_in = False
                try:
                    # is_logged_in is a PROPERTY on neonize NewAClient
                    # (verified 2026-05-20). Drop the parens; getter may
                    # return bool or awaitable. Mirrors PR #599's
                    # heartbeat fix.
                    res = client.is_logged_in
                    if inspect.isawaitable(res):
                        logged_in = await asyncio.wait_for(res, timeout=2)
                    else:
                        logged_in = bool(res)
                except Exception as e:
                    logger.debug(f"is_logged_in check failed: {e}")
                    pass
                    
                logger.info(f"Active detection probe for {key}: status={status}, connected={connected}, logged_in={logged_in}")
                
                if connected:
                    phone = None
                    try:
                        me = await asyncio.wait_for(client.get_me(), timeout=2)
                        phone = me.User if me else None
                    except Exception:
                        pass
                    logger.info(f"Active detection: {key} is connected as {phone}")
                    status = "connected"
                    self._statuses[key] = "connected"
                    self._qr_codes.pop(key, None)
                    self._update_account_status(tenant_id, account_id, "connected", phone=phone)
                    self._save_session_to_db(tenant_id, account_id, source_event="connected")
                elif logged_in:
                    # Authenticated but not fully connected yet
                    if status != "pairing":
                        status = "connecting"
                        self._statuses[key] = "connecting"
            except Exception as e:
                logger.warning(f"Active detection check failed for {key}: {type(e).__name__}: {e}")

        result = {
            "connected": status == "connected",
            "status": status,
        }
        if status == "connecting":
            result["message"] = "Waiting for QR scan"
        # Include fresh QR if still pairing
        if key in self._qr_codes:
            result["qr_data_url"] = self._qr_codes[key]
        return result

    async def get_status(self, tenant_id: str, account_id: str = "default") -> dict:
        key = self._key(tenant_id, account_id)
        in_memory_status = self._statuses.get(key)

        db = self._get_db()
        try:
            acct = self._get_or_create_account(db, tenant_id, account_id)
            return {
                "channel_type": "whatsapp",
                "account_id": account_id,
                "enabled": acct.enabled,
                "status": in_memory_status or acct.status,
                "connected": (in_memory_status or acct.status) == "connected",
                "phone_number": acct.phone_number,
                "dm_policy": acct.dm_policy,
                "allow_from": acct.allow_from,
                "connected_at": acct.connected_at.isoformat() if acct.connected_at else None,
                "last_error": acct.last_error,
            }
        finally:
            db.close()

    async def send_message(
        self, tenant_id: str, account_id: str = "default",
        to: str = "", message: str = "",
    ) -> dict:
        key = self._key(tenant_id, account_id)
        client = self._clients.get(key)
        if not client:
            return {"status": "error", "error": "WhatsApp not connected"}
        if self._statuses.get(key) != "connected":
            return {"status": "error", "error": f"WhatsApp status: {self._statuses.get(key)}"}

        # Normalize phone number (strip + prefix)
        phone = to.lstrip("+")
        jid = build_jid(phone)

        try:
            resp = await client.send_message(jid, message)
            # Track sent message ID to avoid echo loop
            if resp and hasattr(resp, 'ID') and resp.ID:
                sent_ids = self._sent_message_ids.setdefault(key, set())
                sent_ids.add(resp.ID)
                if len(sent_ids) > 100:
                    sent_ids.pop()
            self._log_event(
                tenant_id, account_id, "message_outbound",
                direction="outbound", remote_id=phone,
                message_content=message,
            )
            return {"status": "sent", "message_id": resp.ID if resp else None}
        except Exception as e:
            logger.exception(f"Failed to send message for {key}")
            return {"status": "error", "error": str(e)}

    async def logout(self, tenant_id: str, account_id: str = "default") -> dict:
        key = self._key(tenant_id, account_id)
        # Prevent auto-reconnect
        self._statuses[key] = "logged_out"
        # Cancel watchdog + heartbeat
        watchdog = self._watchdog_tasks.pop(key, None)
        if watchdog and not watchdog.done():
            watchdog.cancel()
        hb = self._heartbeat_tasks.pop(key, None)
        if hb and not hb.done():
            hb.cancel()
        client = self._clients.get(key)
        if client:
            try:
                await client.logout()
            except Exception:
                pass
            try:
                await client.disconnect()
            except Exception:
                pass
            self._clients.pop(key, None)
            self._qr_codes.pop(key, None)

        task = self._tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

        # Purge the on-disk neonize SQLite session file so the next
        # start_pairing has no credentials to rehydrate and mints a
        # fresh QR. See disable() for the rationale comment + memory
        # references.
        self._purge_local_session_file(tenant_id, account_id, reason="logout")

        self._statuses[key] = "logged_out"
        self._update_account_status(tenant_id, account_id, "logged_out")
        return {"status": "logged_out"}

    async def reconnect(self, tenant_id: str, account_id: str = "default") -> dict:
        # Refuse to re-arm a client during a graceful drain (review C1-1/C1-2).
        if self._draining:
            return {"status": "draining"}
        key = self._key(tenant_id, account_id)
        # Cancel existing watchdog
        old_watchdog = self._watchdog_tasks.pop(key, None)
        if old_watchdog and not old_watchdog.done():
            old_watchdog.cancel()
        # Disconnect existing
        if key in self._clients:
            try:
                await self._clients[key].disconnect()
            except Exception:
                pass
            self._clients.pop(key, None)
        task = self._tasks.pop(key, None)
        if task and not task.done():
            task.cancel()

        # Pre-flight: verify WhatsApp is reachable before connect() —
        # neonize Go code panics (kills process) on TLS handshake timeout.
        reachable = await asyncio.get_event_loop().run_in_executor(
            None, self._is_whatsapp_reachable, self.WHATSAPP_CONNECT_TIMEOUT
        )
        if not reachable:
            logger.warning(f"WhatsApp unreachable, skipping reconnect for {key}")
            self._statuses[key] = "disconnected"
            self._update_account_status(tenant_id, account_id, "disconnected",
                                        error="WhatsApp servers unreachable — will retry")
            return {"status": "unreachable"}

        # Reconnect (will restore session from DB if auth state exists)
        client = self._create_client(tenant_id, account_id)
        self._clients[key] = client
        connect_task = await client.connect()
        self._tasks[key] = connect_task
        # Start watchdog for this new connection
        self._watchdog_tasks[key] = asyncio.ensure_future(
            self._connection_watchdog(key, tenant_id, account_id)
        )
        self._update_account_status(tenant_id, account_id, "connecting")
        return {"status": "reconnecting"}

    async def drain_and_shutdown(
        self, *, drain_deadline: float = None, disconnect_timeout: float = None
    ):
        """Clean shutdown drain (design §1) — the fix for the SIGKILL-mid-write
        corruption AND the restart hang:

          1. mark draining — refuse NEW inbound chat turns,
          2. bounded-wait for in-flight turns to finish (protects the 30–90s
             turns the stop grace existed for, but bounded so a stuck turn
             can't hang the process),
          3. per account: disconnect (bounded), then validated-save under the
             session lock — C1: validate AFTER disconnect; a disconnect
             timeout or failed validation ABORTS the save and keeps the last
             known-good (never overwrites),
          4. final dict cleanup via shutdown().

        Bounded throughout so it always returns well within the container
        stop grace; main.py also wraps it in an overall asyncio.wait_for.
        """
        drain_deadline = (
            drain_deadline if drain_deadline is not None
            else float(os.environ.get("WHATSAPP_DRAIN_DEADLINE_SECONDS", "90"))
        )
        disconnect_timeout = (
            disconnect_timeout if disconnect_timeout is not None
            else float(os.environ.get("WHATSAPP_DISCONNECT_TIMEOUT_SECONDS", "8"))
        )

        self._draining = True

        # 1. Cancel ALL recovery tasks up front so nothing re-arms a client
        #    during the drain window (review C1-2). _auto_reconnect/reconnect
        #    also hard short-circuit on _draining to neutralise any bare
        #    ensure_future callback the drain can't directly cancel.
        for taskmap in (self._heartbeat_tasks, self._stable_reset_tasks,
                        self._watchdog_tasks, self._tasks):
            for t in list(taskmap.values()):
                if t and not t.done():
                    t.cancel()
            taskmap.clear()

        logger.info(
            "WhatsApp drain: starting (inflight=%d, deadline=%.0fs, clients=%d)",
            self._inflight_turns, drain_deadline, len(self._clients),
        )

        # 2. bounded-wait for in-flight chat turns
        waited = 0.0
        step = 1.0
        while self._inflight_turns > 0 and waited < drain_deadline:
            if int(waited) % 5 == 0:
                logger.info(
                    "WhatsApp drain: waiting on %d in-flight turn(s) (%.0fs/%.0fs)",
                    self._inflight_turns, waited, drain_deadline,
                )
            await asyncio.sleep(step)
            waited += step
        if self._inflight_turns > 0:
            logger.warning(
                "WhatsApp drain: %d turn(s) still in-flight at deadline — proceeding to save",
                self._inflight_turns,
            )

        # 2b. Cancel per-sender chat consumers + best-effort "restarting"
        #     notice so a deploy shutdown doesn't strand a mid-turn sender
        #     silently, and stop the dedicated chat executor (Luna review R6).
        try:
            await self._drain_chat_consumers()
        except Exception:
            logger.exception("WhatsApp drain: chat-consumer drain failed")

        # 3. per-account disconnect + validated save, CONCURRENTLY so total
        #    wall-clock is ~one disconnect_timeout window regardless of account
        #    count — a serial N*timeout loop could blow the 165s outer budget
        #    (review C1-3). C1: validate AFTER disconnect; a disconnect timeout
        #    or failed validation aborts the save and keeps the last known-good.
        async def _drain_one(key):
            tenant_id, _, account_id = key.partition(":")
            client = self._clients.get(key)
            # Prevent auto-reconnect racing the teardown.
            self._statuses[key] = "logged_out"
            # Disconnect OUTSIDE the session lock: neonize dispatches the
            # on_disconnected handler, which itself acquires this same lock
            # via _save_session_locked — holding the lock across disconnect
            # could self-deadlock. The lock is only needed for the save.
            if client is not None:
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=disconnect_timeout)
                except asyncio.TimeoutError:
                    logger.warning(
                        "WhatsApp drain: disconnect timed out for %s after %.0fs — "
                        "validation will gate any mid-write save", key, disconnect_timeout,
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("WhatsApp drain: disconnect error for %s", key)
            try:
                async with self._get_session_lock(key):
                    saved = self._save_session_to_db(tenant_id, account_id, source_event="shutdown")
                    if not saved:
                        logger.warning(
                            "WhatsApp drain: no validated save for %s — last known-good preserved", key
                        )
            except Exception:
                logger.exception("WhatsApp drain: error draining %s", key)

        await asyncio.gather(
            *[_drain_one(key) for key in list(self._clients.keys())],
            return_exceptions=True,
        )

        # 4. final cleanup
        await self.shutdown()
        logger.info("WhatsApp drain: complete")

    async def shutdown(self):
        """Gracefully disconnect all clients."""
        for key, task in list(self._watchdog_tasks.items()):
            if not task.done():
                task.cancel()
        self._watchdog_tasks.clear()
        for key, client in list(self._clients.items()):
            try:
                self._statuses[key] = "logged_out"  # Prevent auto-reconnect
                await client.disconnect()
            except Exception:
                pass
        for key, task in list(self._tasks.items()):
            if not task.done():
                task.cancel()
        self._clients.clear()
        self._tasks.clear()
        self._qr_codes.clear()
        self._statuses.clear()
        self._reconnect_counts.clear()
        # Stop the dedicated chat executor if drain_and_shutdown didn't already
        # (e.g. shutdown() called directly). Idempotent — safe to double-call.
        try:
            self._chat_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        logger.info("WhatsApp service shut down")

    async def restore_connections(self):
        """On startup, reconnect all enabled accounts that had a connection.

        Neonize keeps auth state in its SQLite DB, so we don't need phone_number
        to be set — the session will auto-restore if the auth state exists on disk.
        """
        db = self._get_db()
        try:
            accounts = (
                db.query(ChannelAccount)
                .filter(
                    ChannelAccount.channel_type == "whatsapp",
                    ChannelAccount.enabled.is_(True),
                    ChannelAccount.status.in_(["connected", "disconnected", "connecting", "pairing"]),
                )
                .all()
            )
            logger.info(f"WhatsApp restore_connections: found {len(accounts)} accounts to restore")
            tasks = []
            for acct in accounts:
                tenant_id = str(acct.tenant_id)
                account_id = acct.account_id
                
                async def restore(tid, aid, status, phone):
                    logger.info(f"Restoring WhatsApp connection for {tid}:{aid} (status={status}, phone={phone})")
                    try:
                        # Restore neonize SQLite session from PostgreSQL before reconnecting
                        self._restore_session_from_db(tid, aid)
                        await self.reconnect(tid, aid)
                    except Exception:
                        logger.exception(f"Failed to restore {tid}:{aid}")

                tasks.append(restore(tenant_id, account_id, acct.status, acct.phone_number))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            db.close()


# Lazy singleton — only initialized when first accessed to avoid
# neonize/protobuf import at module load time (protobuf 7.x vs 6.x conflict).
_whatsapp_service_instance = None

def _get_whatsapp_service():
    global _whatsapp_service_instance
    if _whatsapp_service_instance is None:
        _whatsapp_service_instance = WhatsAppService(db_url=settings.DATABASE_URL)
    return _whatsapp_service_instance

class _LazyWhatsAppService:
    """Proxy that defers WhatsAppService instantiation until first attribute access."""
    def __getattr__(self, name):
        return getattr(_get_whatsapp_service(), name)

whatsapp_service = _LazyWhatsAppService()
