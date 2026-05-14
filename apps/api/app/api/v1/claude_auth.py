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


# How long to wait for the user to paste the code into the UI before
# we give up and tear the subprocess down. 10 min is enough for "open
# the URL → log into claude.com → copy the code → switch tabs → paste"
# without forcing a re-`/start` for slow flows. claude CLI's own
# timeout is on the order of a few minutes; if we wait longer than
# that the subprocess will have exited and the code write will no-op.
_OAUTH_PASTE_DEADLINE_SECONDS = 600

# After we write the code to stdin, how long to wait for claude CLI
# to finish the OAuth handshake and exit. Should be fast (<10s on a
# good network).
_OAUTH_FINALIZE_TIMEOUT = 60


@dataclass
class ClaudeLoginState:
    login_id: str
    tenant_id: str
    # Status machine:
    #   starting           — subprocess spawned, waiting for URL
    #   pending            — URL captured, waiting for user to open browser
    #                        and paste the resulting code into the UI
    #   submitting         — `/submit-code` received the paste; we wrote
    #                        it to subprocess stdin; waiting for claude
    #                        CLI to complete and exit
    #   connected          — credentials persisted to the vault
    #   failed / cancelled — terminal error states
    status: str = "starting"
    verification_url: Optional[str] = None
    error: Optional[str] = None
    connected: bool = False
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    claude_home: Optional[str] = None
    process: Optional[subprocess.Popen] = field(default=None, repr=False, compare=False)
    # Buffer for stdout the reader thread captures while the
    # subprocess runs. We don't use `proc.communicate()` for the
    # whole lifecycle (it consumes stdin / closes pipes), so we
    # collect line-by-line on a background thread instead.
    _output_buf: list = field(default_factory=list, repr=False, compare=False)
    # Signal from `/submit-code` to `_run_login` that the user has
    # pasted a code. The main thread waits on this event before
    # invoking `proc.wait()`.
    _code_submitted: threading.Event = field(
        default_factory=threading.Event, repr=False, compare=False
    )


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
        """Drive the `claude auth login --claudeai` subprocess.

        claude CLI v2.1.140 prints the verification URL on stdout then
        blocks at the `Paste code here if prompted >` prompt reading
        from stdin. The previous implementation used
        `proc.communicate(timeout=5)` to grab the URL, which:
          (a) consumed the stdin pipe so we could never write to it
          (b) returned the buffered output via the
              `TimeoutExpired.output` field — fragile in newer
              Python / subprocess versions where that attribute can
              be empty if the process is fully blocked on a read.
        The result: the subprocess hung forever, the UI never saw the
        URL, and the deploy state machine wedged.

        Rewrite:
          * Spawn with `stdin=PIPE` so `/submit-code` can write to it.
          * Drain stdout on a background thread, line-by-line, so we
            can detect the URL without blocking and without closing
            the stdin pipe.
          * Wait on a `threading.Event` (`state._code_submitted`) for
            the user's paste — set by `/submit-code`.
          * Once the code is written, close stdin to signal EOF and
            let claude CLI finish. `proc.wait(timeout=…)` reaps the
            exit status.
          * On exit, persist credentials from `CLAUDE_CONFIG_DIR`.
        """
        cmd = ["claude", "auth", "login", "--claudeai"]
        env = {**os.environ, "CLAUDE_CONFIG_DIR": state.claude_home or ""}

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                bufsize=1,  # line-buffered so the URL line surfaces immediately
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

        # ── stdout reader thread ─────────────────────────────────
        # Reads line-by-line into state._output_buf so we can detect
        # the verification URL without consuming stdin. The thread
        # exits naturally when proc closes stdout (i.e. when claude
        # CLI exits).
        def _drain_stdout():
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    state._output_buf.append(line)
                    if not state.verification_url:
                        cleaned = self._clean_output(line)
                        url = URL_RE.search(cleaned)
                        if not url:
                            url = re.search(r"https://[^\s]+", cleaned)
                        if url:
                            state.verification_url = url.group(0)
                            # Promote to "pending" the moment we have a
                            # URL — UI starts polling immediately.
                            if state.status == "starting":
                                state.status = "pending"
            except Exception:
                # Reader thread errors aren't fatal — the main thread
                # observes proc.returncode and surfaces failure via
                # the buffered output.
                logger.debug("claude_auth stdout reader exited", exc_info=True)

        reader = threading.Thread(target=_drain_stdout, daemon=True)
        reader.start()

        # ── Wait for URL (max 10s) ───────────────────────────────
        # If the URL never appears something is wrong with the
        # subprocess (claude CLI may have changed flags, claude_home
        # may be unwritable, etc.). Fail fast.
        url_deadline = time.time() + 10
        while time.time() < url_deadline and state.status == "starting":
            if proc.poll() is not None:
                # Subprocess exited before we got a URL — surface its
                # combined output as the error.
                cleaned = self._clean_output("".join(state._output_buf))
                state.status = "failed"
                state.error = cleaned[-500:] if cleaned else (
                    "Claude CLI exited before printing a verification URL"
                )
                state.completed_at = datetime.utcnow().isoformat()
                self._cleanup(state)
                return
            time.sleep(0.2)

        if state.status == "starting":
            # No URL after 10s but proc still running — older fallback.
            cleaned = self._clean_output("".join(state._output_buf))
            self._parse_initial_output(state, cleaned)
            if state.status == "failed":
                if proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                state.completed_at = datetime.utcnow().isoformat()
                self._cleanup(state)
                return

        # ── Wait for /submit-code to fire, or for cancellation ──
        # `state._code_submitted` is set by `claude_auth_submit_code`
        # endpoint after writing the user's pasted code to stdin.
        # While waiting we also poll for the subprocess exiting on
        # its own (timeout / claude.com refused) and for explicit
        # cancellation.
        paste_deadline = time.time() + _OAUTH_PASTE_DEADLINE_SECONDS
        while time.time() < paste_deadline:
            if state.status == "cancelled":
                if proc.poll() is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                self._cleanup(state)
                return
            if state._code_submitted.is_set():
                break
            if proc.poll() is not None:
                # Subprocess died while waiting for paste — claude.com
                # may have refused, or the code TTL expired.
                cleaned = self._clean_output("".join(state._output_buf))
                state.status = "failed"
                state.error = cleaned[-500:] if cleaned else (
                    "Claude CLI exited while waiting for verification code"
                )
                state.completed_at = datetime.utcnow().isoformat()
                self._cleanup(state)
                return
            time.sleep(0.5)
        else:
            # Loop fell through without break or return → paste deadline expired.
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            state.status = "failed"
            state.error = (
                f"Timed out waiting for verification code ({_OAUTH_PASTE_DEADLINE_SECONDS // 60} min). "
                "Open the verification URL in a browser, copy the code, and try again."
            )
            state.completed_at = datetime.utcnow().isoformat()
            self._cleanup(state)
            return

        # ── Code was submitted. Wait for proc to finish. ─────────
        try:
            proc.wait(timeout=_OAUTH_FINALIZE_TIMEOUT)
        except subprocess.TimeoutExpired:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            state.status = "failed"
            state.error = (
                f"Claude CLI did not finish within {_OAUTH_FINALIZE_TIMEOUT}s "
                "after the code was submitted. Try again."
            )
            state.completed_at = datetime.utcnow().isoformat()
            self._cleanup(state)
            return

        # Drain reader thread so any final lines are in the buffer.
        reader.join(timeout=2)

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
            cleaned = self._clean_output("".join(state._output_buf))
            state.status = "failed"
            state.error = cleaned[-500:] if cleaned else "Claude authorization failed"

        state.completed_at = datetime.utcnow().isoformat()
        self._cleanup(state)

    def submit_code(self, tenant_id: str, code: str) -> ClaudeLoginState:
        """Pipe the user-pasted verification code to the running
        subprocess's stdin and signal `_run_login` to wait for proc
        exit.

        Called from the `/submit-code` route. Strips whitespace +
        wrapping quotes from the paste, writes one line terminated
        with `\\n` (claude CLI's prompt reads a line), then closes
        stdin to surface EOF in case the CLI expects it.

        Raises HTTPException on caller errors (no active flow, wrong
        state, etc.); the route handler surfaces them as 400/404.
        """
        with self._lock:
            state = self._by_tenant.get(tenant_id)
        if not state:
            raise HTTPException(status_code=404, detail="No active Claude login flow. Start one with `/start`.")
        if state.status != "pending":
            raise HTTPException(
                status_code=400,
                detail=f"Login is in state '{state.status}', not 'pending'. Cannot accept code.",
            )
        if not state.process or state.process.poll() is not None:
            raise HTTPException(
                status_code=400,
                detail="Claude CLI subprocess is no longer running. Re-run `/start`.",
            )

        # Normalise paste: strip whitespace + surrounding quotes (users
        # commonly copy with trailing newline or paste a quoted token).
        clean_code = code.strip()
        if (clean_code.startswith('"') and clean_code.endswith('"')) or (
            clean_code.startswith("'") and clean_code.endswith("'")
        ):
            clean_code = clean_code[1:-1].strip()
        if not clean_code:
            raise HTTPException(status_code=400, detail="Verification code is empty.")

        try:
            assert state.process.stdin is not None
            state.process.stdin.write(clean_code + "\n")
            state.process.stdin.flush()
            state.process.stdin.close()
        except (BrokenPipeError, OSError) as exc:
            # Subprocess died between our state check and the write.
            raise HTTPException(
                status_code=400,
                detail=f"Could not deliver code to Claude CLI: {exc}. Re-run `/start`.",
            )

        state.status = "submitting"
        state._code_submitted.set()
        return state

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
        # Whether the UI should render the "Paste your code" input.
        # Mirrors `status == 'pending'` but spelled out as a boolean
        # so the UI doesn't have to know the exact state-machine
        # vocabulary. `submitting` and `connected` close the input.
        "awaiting_code": bool(state and state.status == "pending"),
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


# ── Submit-code path (option b: stdin-forward) ─────────────────────────────


class ClaudeSubmitCodeRequest(BaseModel):
    """Payload for `/submit-code` — the verification code claude.com
    showed the user after they authorized in the browser."""

    code: str = Field(
        ...,
        min_length=4,
        description="The verification code from claude.com (typically a short alphanumeric token).",
    )


@router.post("/submit-code")
def claude_auth_submit_code(
    body: ClaudeSubmitCodeRequest,
    current_user: User = Depends(deps.get_current_active_user),
    db: Session = Depends(deps.get_db),
):
    """Forward a user-pasted verification code to the running claude
    CLI subprocess via stdin.

    This is the SECOND half of the subscription-OAuth flow. The first
    half (`/start`) spawned `claude auth login --claudeai` and surfaced
    the verification URL. The user opened that URL in a browser,
    authorized on claude.com, and got back a code. This endpoint pipes
    that code into the subprocess's stdin so it can complete the
    handshake.

    Why this is a separate endpoint instead of folding into `/start`:
    the `/start` call returns immediately with the URL — we can't
    block it waiting for a paste that might be 10 minutes away.
    Separating "I'm ready" from "here's my code" gives the UI a
    natural two-stage flow that mirrors what the user is actually
    doing.

    Status transitions on success:
      pending → submitting → connected
    Status transitions on the various failure modes are documented in
    `ClaudeAuthManager.submit_code`.
    """
    state = _manager.submit_code(str(current_user.tenant_id), body.code)
    connected = _tenant_has_claude_credential(db, current_user.tenant_id)
    return _serialize_state(state, connected=connected)
