"""Claude Code CLI OAuth login flow.

Same pattern as codex_auth.py — spawns `claude auth login`, captures the
browser verification URL, waits for user to authenticate, then persists
the resulting OAuth credentials to the encrypted vault.
"""
import glob
import json
import logging
import os
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
from sqlalchemy.orm import Session

from app.api import deps
from app.db.session import SessionLocal
from app.models.integration_config import IntegrationConfig
from app.models.integration_credential import IntegrationCredential
from app.services.orchestration.credential_vault import store_credential

logger = logging.getLogger(__name__)

router = APIRouter()

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
URL_RE = re.compile(r"https://claude\.com/[^\s]+")


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

            # Store the OAuth token
            store_credential(
                db,
                integration_config_id=config.id,
                tenant_id=tid,
                credential_key="session_token",
                plaintext_value=oauth_token,
                credential_type="oauth_token",
            )

            # Revoke old manual tokens
            legacy = (
                db.query(IntegrationCredential)
                .filter(
                    IntegrationCredential.integration_config_id == config.id,
                    IntegrationCredential.tenant_id == tid,
                    IntegrationCredential.credential_key == "session_token",
                    IntegrationCredential.status == "active",
                )
                .all()
            )
            # Keep only the newest
            if len(legacy) > 1:
                for old in legacy[1:]:
                    old.status = "revoked"
                db.commit()

        finally:
            db.close()

    def _cleanup(self, state: ClaudeLoginState) -> None:
        if state.claude_home and os.path.isdir(state.claude_home):
            try:
                import shutil
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


# ── API Routes ──────────────────────────────────────────────────────────────

@router.post("/start")
async def claude_auth_start(
    current_user: dict = Depends(deps.get_current_user),
    db: Session = Depends(deps.get_db),
):
    """Start Claude Code OAuth login flow. Returns verification URL for browser."""
    tenant_id = str(current_user.tenant_id)
    state = _manager.start_login(tenant_id)

    # Wait briefly for URL to appear
    for _ in range(10):
        if state.verification_url or state.status in {"failed", "cancelled"}:
            break
        time.sleep(0.5)

    return {
        "login_id": state.login_id,
        "status": state.status,
        "verification_url": state.verification_url,
        "connected": state.connected,
        "error": state.error,
    }


@router.get("/status")
async def claude_auth_status(
    current_user: dict = Depends(deps.get_current_user),
):
    """Check Claude Code login flow status."""
    state = _manager.get_state(str(current_user.tenant_id))
    if not state:
        return {"status": "idle", "connected": False}
    return {
        "login_id": state.login_id,
        "status": state.status,
        "verification_url": state.verification_url,
        "connected": state.connected,
        "error": state.error,
    }


@router.post("/cancel")
async def claude_auth_cancel(
    current_user: dict = Depends(deps.get_current_user),
):
    """Cancel an in-progress Claude Code login flow."""
    state = _manager.cancel_login(str(current_user.tenant_id))
    if not state:
        return {"status": "idle", "connected": False}
    return {
        "status": state.status,
        "connected": state.connected,
        "error": state.error,
    }
