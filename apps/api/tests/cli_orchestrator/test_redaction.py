"""Redaction unit tests — design §5.

Coverage:

* Per-rule positive (each redaction rule fires)
* Per-rule negative (similar but legitimate string survives)
* Concatenated-leak test (50KB log line with multiple secrets)
* Randomised property test — secret embedded in random surrounding
  text, secret never survives. (We use a seeded ``random.Random``
  instead of pulling in ``hypothesis`` as a new dep — Phase 1 is
  meant to be a thin slice; Phase 2 can promote to hypothesis if it
  buys real value.)
* Negative-redaction property test (review I6) — pure prose with the
  words "token / key / secret / authorization / password" but NO
  actual secret values; output must equal input byte-for-byte. Catches
  over-redaction that would mask a real incident with a fresh one.
* ``cleanup_codex_home`` happy path + idempotent + tolerant of a
  permission error.
* ``redact_json_structural`` walks dicts and lists, replaces sensitive
  keys, leaves the rest alone.
"""
from __future__ import annotations

import os
import random
import string
import tempfile
from pathlib import Path

import pytest

from app.services.cli_orchestrator.redaction import (
    SENSITIVE_ENV_KEYS,
    cleanup_codex_home,
    redact,
    redact_json_structural,
)


# --------------------------------------------------------------------------
# Per-rule positive tests
# --------------------------------------------------------------------------

class TestRedactPositive:
    def test_rule_1_authorization_bearer(self):
        out = redact("Authorization: Bearer abc123-DEF.456")
        assert "abc123-DEF.456" not in out
        assert "<redacted>" in out

    def test_rule_2_x_internal_key_header(self):
        out = redact("X-Internal-Key: dev_mcp_key_12345")
        assert "dev_mcp_key_12345" not in out
        assert "<redacted>" in out

    def test_rule_2_x_api_key_header(self):
        out = redact("X-Api-Key: my-api-key-value-here")
        assert "my-api-key-value-here" not in out

    def test_rule_2_x_tenant_id_header(self):
        out = redact("X-Tenant-Id: 752626d9-8b2c-4aa2-87ef-c458d48bd38a")
        assert "752626d9" not in out

    def test_rule_3_github_url_token_leak(self):
        # workflows.py:1074 shape — the original prod leak
        leaked = "git push https://ghp_abcdefghijklmnopqrstuvwx@github.com/org/repo.git"
        out = redact(leaked)
        # Either the GH-URL rule (3) or the GH-PAT rule (4) catches it.
        assert "ghp_abcdefghijklmnopqrstuvwx" not in out

    def test_rule_4_github_pat_ghp(self):
        out = redact("token=ghp_aaaaaaaaaaaaaaaaaaaa")
        assert "ghp_aaaaaaaaaaaaaaaaaaaa" not in out
        assert "<redacted-github-token>" in out

    def test_rule_4_github_pat_gho(self):
        out = redact("got gho_bbbbbbbbbbbbbbbbbbbb back from oauth")
        assert "gho_bbbbbbbbbbbbbbbbbbbb" not in out

    def test_rule_5_anthropic_key(self):
        out = redact("ANTHROPIC_API_KEY=sk-ant-api03-aaaaaaaaaaaaaaaaaaaa")
        assert "sk-ant-api03-aaaaaaaaaaaaaaaaaaaa" not in out
        assert "<redacted-api-key>" in out

    def test_rule_5_openai_key(self):
        out = redact("openai key sk-proj-aaaaaaaaaaaaaaaaaaaa for completion")
        assert "sk-proj-aaaaaaaaaaaaaaaaaaaa" not in out

    def test_rule_6_set_cookie(self):
        out = redact("Set-Cookie: session=abc123; HttpOnly; Path=/")
        assert "session=abc123" not in out
        assert "<redacted-cookie>" in out

    def test_rule_6_cookie(self):
        out = redact("Cookie: foo=bar; baz=qux")
        assert "foo=bar" not in out

    def test_rule_7_jwt_shape(self):
        # Three base64url-shaped segments separated by dots.
        jwt = (
            "eyJhbGciOiJIUzI1NiJ9"
            ".eyJzdWIiOiIxMjM0NTYifQ"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        out = redact(f"got back {jwt} as auth")
        assert jwt not in out
        assert "<redacted-jwt>" in out

    def test_rule_8a_config_line_password(self):
        out = redact("password = hunter2-not-a-real-pw")
        assert "hunter2-not-a-real-pw" not in out

    def test_rule_8a_config_line_secret(self):
        out = redact("secret: my-rotating-secret-value")
        assert "my-rotating-secret-value" not in out

    def test_rule_8a_config_line_refresh_token(self):
        out = redact("refresh_token = 1//refresh-token-shape-xyz")
        assert "1//refresh-token-shape-xyz" not in out

    def test_rule_8b_authorization_header_anywhere(self):
        out = redact("trailing log: authorization: Bearer-abc more text")
        # 8b fires (authorization header anywhere), or rule 1 fires
        # (Bearer prefix). Either way the token must be gone.
        assert "Bearer-abc" not in out


# --------------------------------------------------------------------------
# Per-rule negative tests — legitimate strings must survive unchanged
# --------------------------------------------------------------------------

class TestRedactNegative:
    """Each negative test feeds a string that LOOKS sensitive at a glance
    but contains no actual secret. The output must be byte-identical."""

    @pytest.mark.parametrize(
        "prose",
        [
            "the api key was rotated yesterday",
            "Please set your authorization headers carefully.",
            "the token was invalid and we asked the user to retry",
            "a secret from the database is now public",
            "store the password in a secure password manager",
            "the cookie banner asks for consent on every page",
            "the api_key field accepts a string value",
            "rotate keys on a schedule",
            "encrypt secrets at rest",
        ],
    )
    def test_prose_with_secret_words_survives(self, prose):
        # The whole point of review I6: prose should pass untouched.
        assert redact(prose) == prose

    def test_keypair_assignment_survives(self):
        # The classic over-redaction case — `keypair = ed25519` is a
        # legit identifier, not a config-line. Rule 8a's name list does
        # NOT include "keypair", so this MUST survive.
        line = "keypair = ed25519"
        assert redact(line) == line

    def test_colon_in_user_message_survives(self):
        # User chat message containing a word + colon + value with no
        # secret-name token at line start. Rule 8a anchors on line
        # start, so this passes through.
        line = "the user said: hello, how are you today"
        assert redact(line) == line

    def test_random_uuid_survives(self):
        # UUIDs look hex-y but aren't secret-shaped enough to match any
        # rule. The classifier-side "X-Tenant-Id" header rule does
        # match — but only when the header label is present.
        line = "session id 752626d9-8b2c-4aa2-87ef-c458d48bd38a"
        assert redact(line) == line


# --------------------------------------------------------------------------
# Concatenated-leak test — many secrets in one string
# --------------------------------------------------------------------------

def _padding(rng: random.Random, n: int) -> str:
    """Random non-secret padding (letters, digits, spaces, punctuation)."""
    alphabet = string.ascii_letters + string.digits + " .,;\n"
    return "".join(rng.choice(alphabet) for _ in range(n))


def test_concatenated_50kb_leak():
    """A 50KB log line containing a Bearer token, a JWT, an Anthropic key
    and a GH-URL token — every secret must be redacted, every non-
    secret character preserved (verified by checking the secret strings
    are absent and the output length is non-zero)."""
    rng = random.Random(1608)
    bearer = "Authorization: Bearer ABC.def-123"
    jwt = (
        "eyJhbGciOiJIUzI1NiJ9"
        ".eyJzdWIiOiIxMjM0NTYifQ"
        ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    ant_key = "sk-ant-api03-aaaaaaaaaaaaaaaaaaaa"
    git_url = "https://ghp_zzzzzzzzzzzzzzzzzzzz@github.com/org/repo.git"

    # ~50KB of random padding split among the secrets.
    chunks = [_padding(rng, 12_500) for _ in range(4)]
    blob = (
        chunks[0] + bearer
        + chunks[1] + jwt
        + chunks[2] + ant_key
        + chunks[3] + git_url
    )

    out = redact(blob)

    # Every secret is gone.
    assert "ABC.def-123" not in out
    assert jwt not in out
    assert ant_key not in out
    assert "ghp_zzzzzzzzzzzzzzzzzzzz" not in out

    # Output is still substantial — over-redaction would shrink it
    # dramatically.
    assert len(out) > 40_000


# --------------------------------------------------------------------------
# Property tests — randomised
# --------------------------------------------------------------------------

# Phase 1 substitutes hypothesis with a seeded random.Random sweep.
# 200 iterations is enough to catch positional regressions while
# keeping the test under a second.

def _random_text(rng: random.Random, n: int) -> str:
    alphabet = string.ascii_letters + string.digits + " \n.,;:!?-"
    return "".join(rng.choice(alphabet) for _ in range(n))


class TestRedactProperty:
    def test_secret_never_survives_random_surroundings(self):
        """200 trials: pick a secret shape, embed it in random text,
        assert the secret literal is absent from the output."""
        rng = random.Random(20260509)

        # Generators for the secret shapes. Each returns (literal, prefix
        # required to make the rule fire if any).
        generators = [
            lambda: ("Authorization: Bearer "
                     + "".join(rng.choices(string.ascii_letters + string.digits + ".-_", k=24)),
                     None),
            lambda: ("ghp_" + "".join(rng.choices(string.ascii_letters + string.digits, k=36)), None),
            lambda: ("sk-ant-" + "".join(rng.choices(string.ascii_letters + string.digits + "-_", k=40)), None),
            lambda: ("eyJ" + "".join(rng.choices(string.ascii_letters + string.digits + "-_", k=18))
                     + ".eyJ" + "".join(rng.choices(string.ascii_letters + string.digits + "-_", k=18))
                     + "." + "".join(rng.choices(string.ascii_letters + string.digits + "-_", k=22)),
                     None),
        ]

        for _ in range(200):
            secret, _prefix = rng.choice(generators)()
            before = _random_text(rng, rng.randint(0, 200))
            after = _random_text(rng, rng.randint(0, 200))
            blob = before + secret + after
            out = redact(blob)
            # The secret literal MUST be gone — the only acceptable
            # presence is the redaction marker substitute.
            assert secret not in out, (
                f"secret survived redaction: {secret!r} in output starting with {out[:80]!r}"
            )

    def test_negative_redaction_property_pure_prose(self):
        """Review I6: prose containing words like "token / key / secret /
        authorization / password" but NO actual secret values must
        survive byte-for-byte. Over-redaction here is a worse failure
        than under-redaction because it would mask real incidents
        with synthetic ones."""
        rng = random.Random(0xDEADBEEF)
        # Prose corpus of safe sentences containing trigger words.
        sentences = [
            "the token expired and the user re-authenticated",
            "rotate your password every ninety days",
            "secrets management is a security concern",
            "authorization is a separate concern from authentication",
            "the api key field is documented in the schema",
            "store cookies in localStorage instead",
            "auth flow is OAuth 2.0 with PKCE",
            "key insight: caching reduces latency",
            "the session token reference appears in the spec",
            "see the password reset flow diagram",
        ]
        for _ in range(200):
            n = rng.randint(1, 5)
            blob = " ".join(rng.choices(sentences, k=n))
            # Sometimes add leading whitespace / quote markers to test
            # the line-anchored rule 8a's behaviour around prose.
            if rng.random() < 0.3:
                blob = "  " + blob
            if rng.random() < 0.3:
                blob = "> " + blob
            out = redact(blob)
            assert out == blob, (
                f"over-redaction: prose changed.\n"
                f"  input:  {blob!r}\n"
                f"  output: {out!r}"
            )

    # ────────────────────────────────────────────────────────────────
    # Rule 8a config-line shape — the boundary cases.
    #
    # Independent review (commit 1fc0d012) flagged that the property test
    # corpus above never exercises the `<trigger>:<value>` shape on
    # benign-but-config-shaped prose. Rule 8a is line-anchored on
    # `^[\s>]*<trigger>\s*[:=]\s*\S+`, so anything starting a line with
    # `secret:` / `password:` / `api_key=` matches — even a chat
    # sentence like "secret: meeting at 3pm".
    #
    # The team's accepted trade-off: err on the side of over-redaction.
    # If a chat user happens to write a line that looks like a config
    # entry, we'd rather mangle the words than risk leaking an actual
    # secret. These tests pin the trade-off so a future tightening is a
    # deliberate, reviewable change — not a silent rule edit.
    # ────────────────────────────────────────────────────────────────

    def test_rule8a_redacts_real_config_line_shape(self):
        """A real config line containing secret material gets redacted.
        This is rule 8a's primary purpose."""
        out = redact("password=hunter2-actual-prod-pw")
        assert "password=<redacted>" in out
        assert "hunter2" not in out

    def test_rule8a_overredacts_benign_chat_with_colon_value(self):
        """ACCEPTED OVER-REDACTION: chat prose that happens to start with
        a trigger keyword followed by `:` or `=` and a value has its
        FIRST whitespace-delimited token replaced (`\\S+` is the value
        capture). The replacement template is `\\1=<redacted>` — so
        `:` and `=` both normalize to `=` in output, deterministic.

        We accept this trade-off — losing one word from a sentence is
        preferable to leaking a real secret. If a future change tightens
        rule 8a (e.g., requires the value to look secret-shaped), update
        this test to reflect the new behaviour."""
        out = redact("secret: meeting at 3pm in conference room B")
        # `\S+` is non-greedy on the value side: only the first
        # whitespace-delimited token after "secret:" gets eaten. The
        # rest of the line ("at 3pm in conference room B") survives.
        assert out == "secret=<redacted> at 3pm in conference room B"
        # The first word after the colon is gone; the rest is intact.
        assert "<redacted>" in out
        assert "conference room B" in out
        assert "meeting" not in out

    def test_rule8a_does_not_match_trigger_without_assignment(self):
        """No `:` or `=` after the trigger keyword → rule 8a does NOT
        fire. Prose like "the secret to X is Y" survives intact, even
        though it contains the word 'secret'. This is the boundary that
        keeps the rule from being completely greedy."""
        text = "the secret to good code is simplicity"
        assert redact(text) == text

    def test_rule8a_indented_config_line_still_redacts(self):
        """The `^[\\s>]*` prefix in rule 8a allows leading whitespace and
        quote markers (for forwarded email / quoted log lines) to still
        match. Verifies the anchoring is correct."""
        for prefix in ("  ", "    ", "> ", ">> "):
            out = redact(f"{prefix}api_key=AKIAIOSFODNN7EXAMPLE")
            assert "<redacted>" in out
            assert "AKIAIOSFODNN7EXAMPLE" not in out

    def test_rule8a_keyword_in_middle_of_line_does_not_match(self):
        """Rule 8a is line-anchored; a trigger keyword appearing
        mid-sentence (not at line start, modulo whitespace) does not
        fire. This is what keeps "the value of secret=42 is important"
        ambiguous — line-start matters."""
        # Mid-line: "see secret=foo" — rule 8a is line-anchored so this
        # does NOT match (the leading "see " is not whitespace-only).
        text = "see secret=foo for the relevant constant"
        assert redact(text) == text


# --------------------------------------------------------------------------
# redact_json_structural
# --------------------------------------------------------------------------

class TestRedactJsonStructural:
    def test_top_level_sensitive_keys_redacted(self):
        payload = {
            "auth_token": "abc",
            "username": "alice",
        }
        out = redact_json_structural(payload)
        assert out["auth_token"] == "<redacted>"
        assert out["username"] == "alice"

    def test_nested_sensitive_keys_redacted(self):
        payload = {
            "session": {
                "user_id": "u1",
                "access_token": "secret-xyz",
                "metadata": {"client_secret": "abc", "kind": "oauth"},
            },
        }
        out = redact_json_structural(payload)
        assert out["session"]["user_id"] == "u1"
        assert out["session"]["access_token"] == "<redacted>"
        assert out["session"]["metadata"]["client_secret"] == "<redacted>"
        assert out["session"]["metadata"]["kind"] == "oauth"

    def test_list_of_dicts(self):
        payload = [{"api_key": "k1", "name": "a"}, {"api_key": "k2", "name": "b"}]
        out = redact_json_structural(payload)
        assert out == [
            {"api_key": "<redacted>", "name": "a"},
            {"api_key": "<redacted>", "name": "b"},
        ]

    def test_does_not_mutate_input(self):
        payload = {"token": "abc", "list": [{"secret": "s"}]}
        original_token = payload["token"]
        original_list_secret = payload["list"][0]["secret"]
        _ = redact_json_structural(payload)
        assert payload["token"] == original_token
        assert payload["list"][0]["secret"] == original_list_secret

    def test_non_string_keys_pass_through(self):
        payload = {1: "a", 2: {"key": "secret-val"}}
        out = redact_json_structural(payload)
        assert out[1] == "a"
        assert out[2]["key"] == "<redacted>"

    def test_scalars_and_none_pass_through(self):
        # Top-level non-container input is returned unchanged.
        assert redact_json_structural(42) == 42
        assert redact_json_structural("hello") == "hello"
        assert redact_json_structural(None) is None


# --------------------------------------------------------------------------
# cleanup_codex_home
# --------------------------------------------------------------------------

class TestCleanupCodexHome:
    def test_happy_path_removes_directory(self, tmp_path):
        codex = tmp_path / ".codex"
        codex.mkdir()
        (codex / "auth.json").write_text('{"oauth": "secret"}')
        (codex / "config.toml").write_text("[trust]\nlevel=\"trusted\"\n")
        cleanup_codex_home(codex)
        assert not codex.exists()

    def test_idempotent_when_directory_missing(self, tmp_path):
        # Calling on a path that doesn't exist must not raise.
        missing = tmp_path / ".codex-missing"
        cleanup_codex_home(missing)
        cleanup_codex_home(missing)  # second call still fine

    def test_handles_file_at_path(self, tmp_path):
        # Codex auth.json may be at the literal path if the orchestrator
        # decides to clean a file rather than a dir. Don't crash.
        leaf = tmp_path / "auth.json"
        leaf.write_text("secret")
        cleanup_codex_home(leaf)
        assert not leaf.exists()

    def test_tolerates_permission_error(self, tmp_path, monkeypatch):
        codex = tmp_path / ".codex"
        codex.mkdir()
        (codex / "auth.json").write_text("secret")

        # Force shutil.rmtree to raise PermissionError; ignore_errors=True
        # in the helper should swallow it. We verify the helper does
        # NOT propagate.
        import shutil

        def _boom(path, ignore_errors=False, onerror=None):
            if not ignore_errors:
                raise PermissionError("denied")
            # ignore_errors=True path — return without doing anything;
            # mimics shutil.rmtree's swallow behaviour.
            return

        monkeypatch.setattr(shutil, "rmtree", _boom)
        # Should not raise.
        cleanup_codex_home(codex)

    def test_none_input_is_noop(self):
        # Defensive: callers that thread an Optional[str] through must
        # not crash on None.
        cleanup_codex_home(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# SENSITIVE_ENV_KEYS surface check
# --------------------------------------------------------------------------

class TestSensitiveEnvKeys:
    def test_extends_skill_manager_sensitive_set(self):
        """The frozenset must be a strict superset of
        ``skill_manager._SENSITIVE_ENV_KEYS`` plus the four new
        platform-token names. Pin via membership so future drift in
        either set fails this test."""
        from app.services.skill_manager import _SENSITIVE_ENV_KEYS as legacy

        # Every legacy key still present.
        missing = legacy - SENSITIVE_ENV_KEYS
        assert not missing, f"new SENSITIVE_ENV_KEYS dropped legacy keys: {missing}"

        # The four new platform-token names land here.
        for new_key in (
            "CLAUDE_CODE_OAUTH_TOKEN",
            "COPILOT_GITHUB_TOKEN",
            "CODEX_AUTH_JSON",
            "GEMINI_CLI_TOKEN",
        ):
            assert new_key in SENSITIVE_ENV_KEYS, f"missing {new_key}"
