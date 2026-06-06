from __future__ import annotations

import contextlib
import hashlib
import http.client
import hmac
import importlib.util
import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "claudia_bridge", ROOT / "scripts" / "claudia_bridge.py"
)
claudia_bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(claudia_bridge)


@contextlib.contextmanager
def bridge_server(root: Path, secret: str = "shared-secret"):
    claudia_bridge.ensure_queue(root)

    class Handler(claudia_bridge.BridgeHandler):
        pass

    Handler.root = root
    Handler.secret = secret
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def signed_headers(secret: str, raw: bytes) -> dict[str, str]:
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return {
        "content-type": "application/json",
        "x-claudia-signature": f"sha256={digest}",
    }


def post_json(base_url: str, path: str, payload: dict[str, object], secret: str = "shared-secret"):
    raw = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=raw,
        headers=signed_headers(secret, raw),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.status, json.loads(response.read().decode())


def test_create_task_writes_contract_and_queue_dirs(tmp_path):
    code = claudia_bridge.main(
        [
            "--root",
            str(tmp_path / ".claudia"),
            "create",
            "--title",
            "Review bridge plan",
            "--body",
            "Check the hook plus webhook plus GitHub issue contract.",
            "--task-id",
            "bridge-plan",
            "--label",
            "claudia",
        ]
    )

    assert code == 0
    root = tmp_path / ".claudia"
    task = root / "inbox" / "bridge-plan.md"
    assert task.exists()
    for dirname in ("inbox", "status", "outbox", "archive"):
        assert (root / dirname).is_dir()
    body = task.read_text()
    assert "Review bridge plan" in body
    assert "Do not revert user or peer-agent changes." in body
    assert "Check the hook plus webhook plus GitHub issue contract." in body


def test_explicit_task_id_is_filename_safe(tmp_path):
    code = claudia_bridge.main(
        [
            "--root",
            str(tmp_path / ".claudia"),
            "create",
            "--title",
            "Unsafe ID",
            "--body",
            "Body",
            "--task-id",
            "../bad path",
        ]
    )

    assert code == 0
    assert (tmp_path / ".claudia" / "inbox" / "bad-path.md").exists()
    assert not (tmp_path / "bad path.md").exists()


def test_generated_task_ids_are_unique_for_same_title():
    first, _ = claudia_bridge.render_task(
        title="Same title",
        body="Body",
        source="test",
        reply_to="outbox",
        labels=[],
    )
    second, _ = claudia_bridge.render_task(
        title="Same title",
        body="Body",
        source="test",
        reply_to="outbox",
        labels=[],
    )

    assert first != second
    assert first.endswith("-same-title")
    assert second.endswith("-same-title")


def test_custom_root_default_reply_location_points_to_root(tmp_path):
    root = tmp_path / "custom-queue"

    code = claudia_bridge.main(
        [
            "--root",
            str(root),
            "create",
            "--title",
            "Custom root",
            "--body",
            "Body",
            "--task-id",
            "custom-root",
        ]
    )

    assert code == 0
    task = root / "inbox" / "custom-root.md"
    expected_reply_to = root.resolve() / "outbox" / "<task-id>.md"
    assert f"Reply location: `{expected_reply_to}`" in task.read_text()


def test_signature_verification_requires_sha256_hmac():
    secret = "shared-secret"
    raw = json.dumps({"title": "x"}).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    assert claudia_bridge.verify_signature(secret, raw, f"sha256={digest}")
    assert not claudia_bridge.verify_signature(secret, raw, "sha256=bad")
    assert not claudia_bridge.verify_signature(secret, raw, None)
    assert claudia_bridge.verify_signature("", raw, None)


def test_poll_missing_queue_is_read_only(tmp_path, capsys):
    root = tmp_path / ".claudia"

    code = claudia_bridge.main(["--root", str(root), "poll"])

    assert code == 0
    assert "No pending Claudia tasks." in capsys.readouterr().out
    assert not root.exists()


def test_issue_body_renders_without_writing_queue(tmp_path, capsys):
    code = claudia_bridge.main(
        [
            "--root",
            str(tmp_path / ".claudia"),
            "issue-body",
            "--title",
            "Manual consensus with Claudia",
            "--body",
            "Use this as the GitHub issue handoff.",
            "--task-id",
            "consensus",
        ]
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "Manual consensus with Claudia" in output
    assert "Use this as the GitHub issue handoff." in output
    assert not (tmp_path / ".claudia").exists()


def test_webhook_mode_requires_secret_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CLAUDIA_BRIDGE_SECRET", raising=False)

    code = claudia_bridge.main(
        [
            "--root",
            str(tmp_path / ".claudia"),
            "serve",
            "--port",
            "0",
        ]
    )

    assert code == 2
    assert "CLAUDIA_BRIDGE_SECRET is required" in capsys.readouterr().err


def test_webhook_signed_task_writes_to_safe_inbox_path(tmp_path):
    root = tmp_path / ".claudia"

    with bridge_server(root) as base_url:
        status, payload = post_json(
            base_url,
            "/tasks",
            {
                "title": "Webhook task",
                "body": "Review the bridge.",
                "task_id": "../bad path",
            },
        )

    task = root / "inbox" / "bad-path.md"
    assert status == 201
    assert payload["ok"] is True
    assert task.exists()
    assert not (tmp_path / "bad path.md").exists()
    expected_reply_to = root.resolve() / "outbox" / "<task-id>.md"
    assert f"Reply location: `{expected_reply_to}`" in task.read_text()


def test_webhook_signed_outbox_writes_to_safe_outbox_path(tmp_path):
    root = tmp_path / ".claudia"

    with bridge_server(root) as base_url:
        status, payload = post_json(
            base_url,
            "/outbox",
            {
                "task_id": "../bad path",
                "body": "Approved with local-only mailbox first.",
            },
        )

    reply = root / "outbox" / "bad-path.md"
    assert status == 201
    assert payload["ok"] is True
    assert reply.exists()
    assert not (tmp_path / "bad path.md").exists()


def test_webhook_rejects_unsigned_requests(tmp_path):
    root = tmp_path / ".claudia"

    with bridge_server(root) as base_url:
        request = urllib.request.Request(
            f"{base_url}/tasks",
            data=json.dumps({"title": "Unsigned"}).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:  # pragma: no cover - assertion branch
            raise AssertionError("unsigned request was accepted")


def test_webhook_rejects_invalid_content_length(tmp_path):
    root = tmp_path / ".claudia"

    with bridge_server(root) as base_url:
        parsed = urllib.request.urlparse(base_url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        try:
            conn.putrequest("POST", "/tasks")
            conn.putheader("content-length", "not-a-number")
            conn.endheaders()
            response = conn.getresponse()
            assert response.status == 400
            assert b"content-length must be an integer" in response.read()
        finally:
            conn.close()


def test_webhook_rejects_body_over_limit_before_reading(tmp_path):
    root = tmp_path / ".claudia"

    with bridge_server(root) as base_url:
        parsed = urllib.request.urlparse(base_url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
        try:
            conn.putrequest("POST", "/tasks")
            conn.putheader("content-length", str(claudia_bridge.MAX_BODY_BYTES + 1))
            conn.endheaders()
            response = conn.getresponse()
            assert response.status == 413
            assert b"request body exceeds" in response.read()
        finally:
            conn.close()


def test_webhook_times_out_partial_body_before_signature(tmp_path, monkeypatch):
    root = tmp_path / ".claudia"
    monkeypatch.setattr(claudia_bridge, "READ_TIMEOUT_SECONDS", 0.1)

    with bridge_server(root) as base_url:
        parsed = urllib.request.urlparse(base_url)
        with socket.create_connection((parsed.hostname, parsed.port), timeout=2) as conn:
            conn.settimeout(2)
            conn.sendall(
                b"POST /tasks HTTP/1.1\r\n"
                + f"Host: {parsed.hostname}\r\n".encode()
                + b"Content-Type: application/json\r\n"
                + b"Content-Length: 32\r\n\r\n"
                + b"{"
            )
            chunks = []
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            response = b"".join(chunks)

    assert b"400" in response.splitlines()[0]
    assert b"request body read timed out" in response
