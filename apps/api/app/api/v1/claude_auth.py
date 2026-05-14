"""Claude Code CLI OAuth login flow.

Same pattern as codex_auth.py — spawns `claude auth login`, captures the
browser verification URL, waits for user to authenticate, then persists
the resulting OAuth credentials to the encrypted vault.
"""
import glob
import json
import logging
import os
import shutil
import re
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.db.session import SessionLocal
from app.models.integration_config import IntegrationConfig
from app.models.integration_credential import IntegrationCredential
from app.models.user import User
from app.services.orchestration.credential_vault import store_credential

logger = logging.getLogger(__name__)

router = APIRouter()

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
URL_RE = re.compile(r"https://claude\.com/[^\s]+")

# Credential keys we recognise as "Claude Code is connected". Either is a
# valid signal; consumers branch on the credential's `credential_type` to
# pick the auth shape (OAuth `session_token` vs Anthropic Console `api_key`).
_CLAUDE_CREDENTIAL_KEYS = ("session_token", "api_key")


@dataclass
class ClaudeLoginState:
    login_id: str
    tenant_id: str
    status: str = "starting"
    verification_url: Optional[str] = None
    error: Optional[str] = None
    connected: bool = False
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    claude_home: Optional[str] = None
    process: Optional[subprocess.Popen] = field(default=None, repr=False, compare=False)


class ClaudeAuthManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_tenant: Dict[str, ClaudeLoginState] = {}

    def get_state(self, tenant_id: str) -> Optional[ClaudeLoginState]:
        with self._lock:
            return self._by_tenant.get(tenant_id)

    def start_login(self, tenant_id: str) -> ClaudeLoginState:
        with self._lock:
            existing = self._by_tenant.get(tenant_id)
            if existing and existing.status in {"starting", "pending"} and existing.process:
                return existing

            if existing and existing.process and existing.process.poll() is None:
                try:
                    existing.process.terminate()
                except Exception:
                    pass

            login_id = str(uuid.uuid4())
            claude_home = tempfile.mkdtemp(prefix=f"claude-auth-{tenant_id[:8]}-")
            state = ClaudeLoginState(
                login_id=login_id,
                tenant_id=tenant_id,
                claude_home=claude_home,
            )
            self._by_tenant[tenant_id] = state

        threading.Thread(target=self._run_login, args=(state,), daemon=True).start()
        return state

    def cancel_login(self, tenant_id: str) -> Optional[ClaudeLoginState]:
        with self._lock:
            state = self._by_tenant.get(tenant_id)
        if not state:
            return None
        if state.process and state.process.poll() is None:
            try:
                state.process.terminate()
            except Exception:
                pass
        state.status = "cancelled"
        state.error = "Login cancelled"
        state.completed_at = datetime.utcnow().isoformat()
        return state

    def _run_login(self, state: ClaudeLoginState) -> None:
        cmd = ["claude", "auth", "login", "--claudeai"]
        env = {**os.environ, "CLAUDE_CONFIG_DIR": state.claude_home or ""}

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
        except FileNotFoundError:
            state.status = "failed"
            state.error = "Claude CLI not found"
            state.completed_at = datetime.utcnow().isoformat()
            return
        except Exception as exc:
            state.status = "failed"
            state.error = str(exc)
            state.completed_at = datetime.utcnow().isoformat()
            return

        state.process = proc

        # Read initial output to capture the verification URL
        try:
            proc.communicate(timeout=5)
            initial_output = ""
        except subprocess.TimeoutExpired as exc:
            initial_output = self._ensure_text(exc.output)
        except Exception as exc:
            state.status = "failed"
            state.error = str(exc)
            state.completed_at = datetime.utcnow().isoformat()
            return

        self._parse_initial_output(state, initial_output)

        # Wait for user to complete browser auth (up to 5 minutes)
        try:
            remaining_output, _ = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            if proc.poll() is None:
                proc.terminate()
            state.status = "failed"
            state.error = "Login timed out (5 min). Please try again."
            state.completed_at = datetime.utcnow().isoformat()
            self._cleanup(state)
            return
        except Exception as exc:
            state.status = "failed"
            state.error = str(exc)
            state.completed_at = datetime.utcnow().isoformat()
            self._cleanup(state)
            return

        if proc.returncode == 0:
            try:
                self._persist_credentials(state)
                state.status = "connected"
                state.connected = True
                state.error = None
            except Exception as exc:
                logger.exception("Failed to persist Claude auth credentials")
                state.status = "failed"
                state.error = f"Failed to store credentials: {exc}"
        elif state.status != "cancelled":
            combined = (initial_output or "") + self._ensure_text(remaining_output)
            cleaned = self._clean_output(combined)
            state.status = "failed"
            state.error = cleaned[-500:] if cleaned else "Claude authorization failed"

        state.completed_at = datetime.utcnow().isoformat()
        self._cleanup(state)

    def _parse_initial_output(self, state: ClaudeLoginState, output: str) -> None:
        cleaned = self._clean_output(output)
        url_match = URL_RE.search(cleaned)

        if url_match:
            state.verification_url = url_match.group(0)
            state.status = "pending"
        elif not cleaned.strip():
            state.status = "starting"
        else:
            # Might contain the URL in raw output
            for line in cleaned.split("\n"):
                if "claude.com" in line and "http" in line:
                    url = re.search(r"https://[^\s]+", line)
                    if url:
                        state.verification_url = url.group(0)
                        state.status = "pending"
                        return
            state.status = "failed"
            state.error = "Could not read verification URL from Claude CLI"

    def _persist_credentials(self, state: ClaudeLoginState) -> None:
        """Read OAuth credentials from Claude's config dir and store in vault."""
        db: Session = SessionLocal()
        try:
            tid = uuid.UUID(state.tenant_id)

            # Claude stores OAuth token in config dir
            # Look for credentials.json or auth files
            claude_dir = state.claude_home or ""
            oauth_token = None

            # Check common credential locations
            for pattern in [
                os.path.join(claude_dir, "**", "credentials.json"),
                os.path.join(claude_dir, "**", "auth.json"),
                os.path.join(claude_dir, "**", "*.json"),
            ]:
                for path in glob.glob(pattern, recursive=True):
                    try:
                        with open(path) as f:
                            data = json.load(f)
                        # Look for OAuth token fields
                        token = (
                            data.get("oauth_token")
                            or data.get("accessToken")
                            or data.get("access_token")
                            or data.get("token")
                        )
                        if token:
                            oauth_token = token
                            break
                        # If the file itself is the auth payload, store it whole
                        if any(k in data for k in ("refresh_token", "expires_at", "session_key")):
                            oauth_token = json.dumps(data)
                            break
                    except (json.JSONDecodeError, IOError):
                        continue

            if not oauth_token:
                # Fallback: check claude auth status for the token
                try:
                    result = subprocess.run(
                        ["claude", "auth", "status", "--json"],
                        capture_output=True, text=True, timeout=10,
                        env={**os.environ, "CLAUDE_CONFIG_DIR": claude_dir},
                    )
                    if result.returncode == 0:
                        status_data = json.loads(result.stdout.strip().split("\n")[0])
                        if status_data.get("loggedIn"):
                            # Store the entire config dir content as the credential
                            oauth_token = json.dumps(status_data)
                except Exception:
                    pass

            if not oauth_token:
                # Last resort: store all JSON files from the config dir
                all_files = {}
                for root, _, files in os.walk(claude_dir):
                    for fname in files:
                        if fname.endswith(".json"):
                            fpath = os.path.join(root, fname)
                            try:
                                with open(fpath) as f:
                                    all_files[fname] = json.load(f)
                            except Exception:
                                pass
                if all_files:
                    oauth_token = json.dumps(all_files)

            if not oauth_token:
                raise RuntimeError("No OAuth credentials found after login")

            # Find or create integration config
            config = (
                db.query(IntegrationConfig)
                .filter(
                    IntegrationConfig.tenant_id == tid,
                    IntegrationConfig.integration_name == "claude_code",
                )
                .first()
            )
            if not config:
                config = IntegrationConfig(
                    tenant_id=tid,
                    integration_name="claude_code",
                    enabled=True,
                )
                db.add(config)
                db.commit()
                db.refresh(config)
            elif not config.enabled:
                config.enabled = True
                db.add(config)
                db.commit()
                db.refresh(config)

            # Revoke any stale credential from the *other* flow so a
            # later read returns only the freshly-stored row.
            # `store_credential` revokes only same-`credential_key` rows
            # (see credential_vault.store_credential filter), so an
            # `api_key` → OAuth swap would otherwise leave the old
            # `api_key` row active and confuse cli_session_manager.
            _revoke_other_claude_credentials(db, config.id, tid, keep="session_token")

            # Store the OAuth token
            store_credential(
                db,
                integration_config_id=config.id,
                tenant_id=tid,
                credential_key="session_token",
                plaintext_value=oauth_token,
                credential_type="oauth_token",
            )

        finally:
            db.close()

    def _cleanup(self, state: ClaudeLoginState) -> None:
        if state.claude_home and os.path.isdir(state.claude_home):
            try:
                shutil.rmtree(state.claude_home, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _ensure_text(output) -> str:
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="ignore")
        return output or ""

    @staticmethod
    def _clean_output(output) -> str:
        return ANSI_RE.sub("", ClaudeAuthManager._ensure_text(output))


_manager = ClaudeAuthManager()


# ── Cross-flow credential housekeeping ──────────────────────────────────────

def _revoke_other_claude_credentials(
    db: Session,
    integration_config_id,
    tenant_id,
    *,
    keep: str,
) -> None:
    """Revoke active claude_code credentials whose `credential_key` is NOT `keep`.

    `store_credential` only revokes rows with the **same** `credential_key`
    (vault filter at credential_vault.py:74-83). The OAuth flow stores
    `credential_key='session_token'` and the API-key flow stores
    `credential_key='api_key'`, so they live in disjoint key namespaces.
    Without this helper, switching flows leaves the other path's row
    active, and `retrieve_credentials_for_skill` returns both — letting
    cli_session_manager silently keep using a stale credential.

    Caller must commit after `store_credential` lands the new row.
    """
    others = [k for k in _CLAUDE_CREDENTIAL_KEYS if k != keep]
    if not others:
        return
    (
        db.query(IntegrationCredential)
        .filter(
            IntegrationCredential.integration_config_id == integration_config_id,
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.credential_key.in_(others),
            IntegrationCredential.status == "active",
        )
        .update({"status": "revoked"}, synchronize_session=False)
    )


# ── API Routes ──────────────────────────────────────────────────────────────

_CLAUDE_CREDENTIAL_KEYS = ("session_token", "api_key")


def _tenant_has_claude_credential(db: Session, tenant_id) -> bool:
    """Check if tenant has a stored Claude Code credential in the vault.

    Recognises **either** the OAuth path (`credential_key='session_token'`,
    written by `_persist_credentials`) **or** the API-key fast-path
    (`credential_key='api_key'`, written by `/api-key`). Either is a
    valid "connected" signal — downstream consumers branch on the
    credential's `credential_type` to pick the auth shape.
    """
    tid = uuid.UUID(str(tenant_id)) if not isinstance(tenant_id, uuid.UUID) else tenant_id
    config = (
        db.query(IntegrationConfig)
        .filter(IntegrationConfig.tenant_id == tid, IntegrationConfig.integration_name == "claude_code")
        .first()
    )
    if not config:
        return False
    cred = (
        db.query(IntegrationCredential)
        .filter(
            IntegrationCredential.integration_config_id == config.id,
            IntegrationCredential.credential_key.in_(_CLAUDE_CREDENTIAL_KEYS),
            IntegrationCredential.status == "active",
        )
        .first()
    )
    return cred is not None


def _serialize_state(state: ClaudeLoginState, connected: bool = False) -> dict:
    return {
        "login_id": state.login_id if state else None,
        "status": state.status if state else "idle",
        "verification_url": state.verification_url if state else None,
        "connected": connected or (state.connected if state else False),
        "error": state.error if state else None,
    }


@router.post("/start")
def claude_auth_start(
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Start Claude Code OAuth login flow. Returns verification URL for browser."""
    tenant_id = str(current_user.tenant_id)
    state = _manager.start_login(tenant_id)

    # Wait briefly for URL to appear (sync handler — runs in thread pool)
    for _ in range(10):
        if state.verification_url or state.status in {"failed", "cancelled"}:
            break
        time.sleep(0.5)

    connected = _tenant_has_claude_credential(db, current_user.tenant_id)
    return _serialize_state(state, connected=connected)


@router.get("/status")
def claude_auth_status(
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Check Claude Code login flow status."""
    state = _manager.get_state(str(current_user.tenant_id))
    connected = _tenant_has_claude_credential(db, current_user.tenant_id)
    if not state:
        return {"status": "idle", "connected": connected}
    return _serialize_state(state, connected=connected)


@router.post("/cancel")
def claude_auth_cancel(
    current_user: User = Depends(deps.get_current_active_user),
):
    """Cancel an in-progress Claude Code login flow."""
    state = _manager.cancel_login(str(current_user.tenant_id))
    if not state:
        return {"status": "idle", "connected": False}
    return _serialize_state(state)


# ── API-key path (option a) ────────────────────────────────────────────────
# The subscription-OAuth flow above spawns `claude auth login --claudeai`
# inside the api container and tries to read its callback / paste-code,
# which is architecturally broken (the container has no browser and no
# way to receive the OAuth callback or feed a paste-code into the
# subprocess's stdin). For users who'd rather paste an Anthropic
# Console API key (`sk-ant-…`), this endpoint stores it directly in the
# credential vault under the same `claude_code` integration name, so
# downstream consumers see the same credential shape — they don't need
# to care which flow produced it.


class ClaudeApiKeyRequest(BaseModel):
    """Payload for `POST /api/v1/claude-auth/api-key`."""

    api_key: str = Field(
        ...,
        min_length=20,
        description="Anthropic Console API key — typically starts with `sk-ant-`.",
    )


@router.post("/api-key")
def claude_auth_set_api_key(
    body: ClaudeApiKeyRequest,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Store a user-supplied Anthropic API key as the tenant's Claude credential.

    Cheap fast-path for users who can't use the subscription-OAuth flow
    (no browser inside the api container) but have an API key.

    Strips wrapping whitespace and any leading `ANTHROPIC_API_KEY=` /
    `Bearer ` prefix paste-from-shell-history users tend to include.
    Validates the `sk-ant-` prefix as a sanity check — Anthropic API
    keys always use it and the wrong prefix usually means a paste
    mistake (whole `claude.ai` cookie, an OpenAI key, etc.). Rejects
    short strings to catch obvious typos.

    Side-effects:
      * Creates `IntegrationConfig(integration_name='claude_code', enabled=True)`
        if absent, matching `_persist_credentials` so downstream readers
        (orchestration, MCP tools) see the same shape regardless of
        which flow stored the credential.
      * Stores the key in the vault with `credential_type='api_key'`
        (vs the OAuth flow's `oauth_token`). Consumers branch on the
        type when calling Anthropic.
      * `store_credential` revokes prior active credentials *with the
        same `credential_key`*. The OAuth path lives under
        `credential_key='session_token'`, this path under
        `credential_key='api_key'`, so swapping flows would otherwise
        leave the other path's row active. We explicitly revoke the
        cross-flow row via `_revoke_other_claude_credentials` to keep
        downstream reads single-rowed.
    """
    raw = _normalise_api_key_paste(body.api_key)

    if not raw.startswith("sk-ant-"):
        raise HTTPException(
            status_code=400,
            detail=(
                "API key must start with `sk-ant-` — that's the Anthropic Console "
                "prefix. If you pasted a Claude.ai session cookie or a "
                "different provider's key, swap it for an Anthropic Console "
                "API key from console.anthropic.com/settings/keys."
            ),
        )

    tid = current_user.tenant_id
    config = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.tenant_id == tid,
            IntegrationConfig.integration_name == "claude_code",
        )
        .first()
    )
    if not config:
        config = IntegrationConfig(
            tenant_id=tid,
            integration_name="claude_code",
            enabled=True,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    elif not config.enabled:
        config.enabled = True
        db.add(config)
        db.commit()
        db.refresh(config)

    # Revoke any stale OAuth `session_token` so downstream readers
    # don't see two active credentials and silently prefer the old one
    # (see _revoke_other_claude_credentials docstring).
    _revoke_other_claude_credentials(db, config.id, tid, keep="api_key")

    store_credential(
        db,
        integration_config_id=config.id,
        tenant_id=tid,
        credential_key="api_key",
        plaintext_value=raw,
        credential_type="api_key",
    )

    return {
        "status": "connected",
        "connected": True,
        "credential_type": "api_key",
    }


# ── Paste-artefact normalisation ────────────────────────────────────────────

# Prefixes a user might accidentally paste alongside the key, matched
# case-insensitively. Order matters: longer/more-specific prefixes come
# first so `export ANTHROPIC_API_KEY=` peels off before
# `ANTHROPIC_API_KEY=`. Each successful match also strips wrapping
# whitespace so YAML-style `KEY:  value` (with extra spaces) works.
_API_KEY_PASTE_PREFIXES = (
    "export ANTHROPIC_API_KEY=",
    "ANTHROPIC_API_KEY=",
    "ANTHROPIC_API_KEY:",
    "x-api-key:",
    "Authorization: Bearer",
    "Authorization:",
    "Bearer",
    "bearer",
)


def _normalise_api_key_paste(raw: str) -> str:
    """Strip wrapping whitespace, common header/.env prefixes, and quotes.

    Idempotent: re-running on the result is a no-op. Case-insensitive
    on prefix matches because users paste shell history (`Bearer`),
    curl examples (`bearer`), and YAML (`x-api-key:`) interchangeably.
    """
    raw = raw.strip()
    raw_lower = raw.lower()
    for prefix in _API_KEY_PASTE_PREFIXES:
        if raw_lower.startswith(prefix.lower()):
            raw = raw[len(prefix):].lstrip(" \t")
            break
    # Strip a *single* layer of wrapping quotes (.env: `KEY="sk-ant-..."`).
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        raw = raw[1:-1].strip()
    return raw
