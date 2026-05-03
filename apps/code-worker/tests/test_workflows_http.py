"""HTTP-boundary tests — internal API token fetch, RL logging, council finalize.

All ``httpx`` calls are mocked; no live network is ever hit.
"""
from __future__ import annotations

import json

import httpx
import pytest

import workflows as wf


# ── _fetch_integration_credentials ───────────────────────────────────────

class TestFetchIntegrationCredentials:
    def test_success_returns_decoded_json(self, monkeypatch):
        captured = {}

        class FakeResp:
            status_code = 200

            def json(self):
                return {"session_token": "tok-123"}

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url, headers=None, params=None):
                captured["url"] = url
                captured["headers"] = headers
                captured["params"] = params
                return FakeResp()

        monkeypatch.setattr(wf.httpx, "Client", FakeClient)

        out = wf._fetch_integration_credentials("claude_code", "tenant-aaa")

        assert out == {"session_token": "tok-123"}
        # The URL must include the integration name and the auth header.
        assert "/oauth/internal/token/claude_code" in captured["url"]
        assert "X-Internal-Key" in captured["headers"]
        assert captured["params"] == {"tenant_id": "tenant-aaa"}

    def test_404_raises_friendly_message(self, monkeypatch):
        class FakeResp:
            status_code = 404

            def raise_for_status(self):
                raise httpx.HTTPStatusError("404", request=None, response=None)

            def json(self):
                return {}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url, headers=None, params=None):
                return FakeResp()

        monkeypatch.setattr(wf.httpx, "Client", FakeClient)

        with pytest.raises(RuntimeError) as excinfo:
            wf._fetch_integration_credentials("claude_code", "tenant-aaa")
        # Friendly canonical message must mention "not connected".
        assert "not connected" in str(excinfo.value).lower()

    def test_unknown_integration_uses_generic_message(self, monkeypatch):
        class FakeResp:
            status_code = 404

            def raise_for_status(self):
                raise httpx.HTTPStatusError("404", request=None, response=None)

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url, headers=None, params=None):
                return FakeResp()

        monkeypatch.setattr(wf.httpx, "Client", FakeClient)

        with pytest.raises(RuntimeError) as excinfo:
            wf._fetch_integration_credentials("does_not_exist", "t-1")
        assert "does_not_exist" in str(excinfo.value)


# ── _fetch_claude_token (sync wrapper around httpx.get) ───────────────────

class TestFetchClaudeToken:
    def _fake_response(self, status: int, payload: dict | None = None):
        class FakeResp:
            status_code = status

            def json(self):
                return payload or {}

        return FakeResp()

    def test_returns_session_token_on_200(self, monkeypatch):
        monkeypatch.setattr(
            wf.httpx,
            "get",
            lambda *a, **kw: self._fake_response(200, {"session_token": "abc"}),
        )
        # The module has TWO _fetch_claude_token defs — the second (line ~1399)
        # wins. It returns ``Optional[str]`` and never raises.
        out = wf._fetch_claude_token("tenant-aaa")
        assert out == "abc"

    def test_returns_none_on_404(self, monkeypatch):
        monkeypatch.setattr(
            wf.httpx, "get", lambda *a, **kw: self._fake_response(404),
        )
        assert wf._fetch_claude_token("tenant-aaa") is None

    def test_swallows_network_errors(self, monkeypatch):
        def boom(*a, **kw):
            raise httpx.ConnectError("conn refused")

        monkeypatch.setattr(wf.httpx, "get", boom)
        assert wf._fetch_claude_token("tenant-aaa") is None


# ── _fetch_github_token — pinned-account flow ───────────────────────────

class TestFetchGithubToken:
    def test_uses_primary_account_pin_when_present(self, monkeypatch):
        seen_calls: list[dict] = []

        def fake_get(url, params=None, headers=None, timeout=None):
            seen_calls.append({"url": url, "params": params})

            class R:
                status_code = 200

                def json(self):
                    if "connected-accounts" in url:
                        return {"primary_account": "user@example.com"}
                    # Token fetch — must include the pinned account_email.
                    assert params.get("account_email") == "user@example.com"
                    return {"oauth_token": "ghp_pinned"}

            return R()

        monkeypatch.setattr(wf.httpx, "get", fake_get)
        out = wf._fetch_github_token("tenant-aaa")
        assert out == "ghp_pinned"
        assert any("connected-accounts" in c["url"] for c in seen_calls)
        assert any("/token/github" in c["url"] for c in seen_calls)

    def test_no_pin_falls_back_to_unscoped_token(self, monkeypatch):
        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 200 if "connected-accounts" not in url else 200

                def json(self):
                    if "connected-accounts" in url:
                        # No pin set.
                        return {"primary_account": None}
                    # account_email must NOT be present.
                    assert "account_email" not in (params or {})
                    return {"session_token": "ghp_unscoped"}

            return R()

        monkeypatch.setattr(wf.httpx, "get", fake_get)
        assert wf._fetch_github_token("tenant-aaa") == "ghp_unscoped"

    def test_pin_404_falls_back_to_unscoped(self, monkeypatch):
        sequence = iter([
            # connected-accounts lookup
            ("primary", 200, {"primary_account": "stale@x.com"}),
            # pinned token fetch — 404
            ("token", 404, {}),
            # fallback token fetch — 200
            ("token", 200, {"oauth_token": "ghp_fallback"}),
        ])

        def fake_get(url, params=None, headers=None, timeout=None):
            kind, status, body = next(sequence)

            class R:
                status_code = status

                def json(self):
                    return body

            return R()

        monkeypatch.setattr(wf.httpx, "get", fake_get)
        assert wf._fetch_github_token("tenant-aaa") == "ghp_fallback"

    def test_returns_none_on_total_failure(self, monkeypatch):
        def fake_get(*a, **kw):
            raise httpx.ConnectError("nope")

        monkeypatch.setattr(wf.httpx, "get", fake_get)
        assert wf._fetch_github_token("tenant-aaa") is None


# ── _log_code_task_rl — must never raise ────────────────────────────────

class TestLogCodeTaskRl:
    def test_swallow_http_failure(self, monkeypatch):
        def boom(*a, **kw):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(wf.httpx, "post", boom)
        # Must not raise.
        wf._log_code_task_rl(
            tenant_id="t-1", branch="b", tag="feat", files_changed=["a.py"], pr_number=1,
        )

    def test_payload_shape(self, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers

            class R:
                status_code = 200

            return R()

        monkeypatch.setattr(wf.httpx, "post", fake_post)
        wf._log_code_task_rl(
            tenant_id="t-1",
            branch="branchx",
            tag="fix",
            files_changed=["a.py", "b.py"],
            pr_number=42,
            platform="claude_code",
        )

        assert "/rl/internal/experience" in captured["url"]
        body = captured["json"]
        assert body["decision_point"] == "code_task"
        assert body["state"]["task_type"] == "fix"
        assert body["action"]["platform"] == "claude_code"
        assert "X-Internal-Key" in captured["headers"]


# ── finalize_provider_council activity ──────────────────────────────────

class TestFinalizeProviderCouncil:
    @pytest.mark.asyncio
    async def test_success_returns_true(self, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            assert "/rl/internal/experience/" in url
            assert url.endswith("/finalize")

            class R:
                status_code = 200

            return R()

        monkeypatch.setattr(wf.httpx, "post", fake_post)
        ok = await wf.finalize_provider_council(
            tenant_id="t-1",
            experience_id="exp-1",
            result_json=json.dumps({"verdict": "APPROVED"}),
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_non_200_returns_false(self, monkeypatch):
        def fake_post(*a, **kw):
            class R:
                status_code = 500

            return R()

        monkeypatch.setattr(wf.httpx, "post", fake_post)
        ok = await wf.finalize_provider_council(
            tenant_id="t-1", experience_id="x", result_json="{}",
        )
        assert ok is False

    @pytest.mark.asyncio
    async def test_exception_returns_false(self, monkeypatch):
        def boom(*a, **kw):
            raise httpx.ConnectError("nope")

        monkeypatch.setattr(wf.httpx, "post", boom)
        ok = await wf.finalize_provider_council(
            tenant_id="t-1", experience_id="x", result_json="{}",
        )
        assert ok is False
