"""PR-D desktop-control contract parity — API side (drift detector).

The API is the canonical owner of the desktop-control contract. These tests
assert the shared golden fixtures in ``docs/contracts/desktop-control/`` stay
display-safe and structurally valid, and — when the service module is importable
— that every enum value in the fixtures is a member of the REAL constants in
``app.services.desktop_control_service``. If the service changes its capability /
status / control-mode / envelope-algorithm sets, the fixtures must be
regenerated; this test fails on that drift.

Scope: contract/parity only. No native actuation; no DB; read-only over fixtures.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# ── locate the shared fixtures dir by ascending to the repo root marker ──
def _fixtures_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "docs" / "contracts" / "desktop-control"
        if cand.is_dir():
            return cand
    raise AssertionError("docs/contracts/desktop-control not found above this test")


FIXTURES = _fixtures_dir()
CLAIM = "pointer_command_claim.display_safe.json"
DENY_BUNDLE = "deny.missing_target_bundle_id.json"
DENY_CAP = "deny.capability_mismatch.json"
OBSERVATION_STATUS = "observation_status.planner_safe.json"
OBSERVATION_FETCH_DENIED = "observation_fetch.denied.json"
GRANT_REQUEST = "grant_request.pending.json"
GRANT_REQUEST_DENIED = "grant_request.denied.json"
GRANT_APPROVAL = "grant_approval.approved.json"
ACTUATE = "actuate.queued.json"

# ── display-safe boundary: these exact keys must never appear, at any depth ──
FORBIDDEN_KEYS = {
    "window_title", "screenshot", "screenshot_b64", "screenshot_bytes",
    "clipboard", "clipboard_text", "ocr_text", "ax_tree", "page_text",
    "signature", "private_key", "raw_title", "title",
}

def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _forbidden_hits(node, path="") -> list[str]:
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FORBIDDEN_KEYS:
                hits.append(f"{path}.{key}")
            hits.extend(_forbidden_hits(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            hits.extend(_forbidden_hits(value, f"{path}[{i}]"))
    return hits


# ── always-runnable: structure + display-safe (no app import) ────────────

@pytest.mark.parametrize(
    "name",
    [
        CLAIM, DENY_BUNDLE, DENY_CAP, OBSERVATION_STATUS, OBSERVATION_FETCH_DENIED,
        GRANT_REQUEST, GRANT_REQUEST_DENIED, GRANT_APPROVAL, ACTUATE,
    ],
)
def test_fixture_is_display_safe(name):
    hits = _forbidden_hits(_load(name))
    assert hits == [], f"{name} leaks raw/forbidden field(s): {hits}"


def test_claim_structure():
    c = _load(CLAIM)
    assert c["kind"] == "command_claim"
    assert c["capability"] == "pointer_control"
    assert c["risk_tier"] == "native_control"
    for key in ("desktop_command_id", "status", "control_mode", "envelope", "target", "action"):
        assert key in c, f"claim missing {key}"
    assert c["envelope"]["schema"] == "agentprovision.desktop_command_envelope.v1"
    assert c["envelope"]["signature_present"] is True
    assert "signature" not in c["envelope"]  # raw signature is Tauri-only
    assert "window_title" not in c["target"] and c["target"]["window_title_hash"]
    assert c["action"]["name"] == "pointer_click"


@pytest.mark.parametrize("name", [DENY_BUNDLE, DENY_CAP])
def test_deny_structure(name):
    d = _load(name)
    assert d["kind"] == "command_denied"
    assert d["status"] == "denied"
    assert d["down_channel_available"] is False
    assert d["code"] and isinstance(d["code"], str)
    assert d["code"] == d["code"].lower() and " " not in d["code"]  # snake/lower code
    for key in ("action", "capability", "reason"):
        assert key in d, f"deny missing {key}"


# ── drift detector: fixtures vs REAL service constants (skips if unimportable) ──

def test_fixtures_match_service_enums():
    svc = pytest.importorskip("app.services.desktop_control_service")
    capabilities = set(svc._OBSERVATION_CAPABILITIES.values()) | set(
        svc._NATIVE_CONTROL_CAPABILITIES.values()
    )
    actions = set(svc._COMMAND_ACTION_CAPABILITIES.keys())
    statuses = set(svc._TERMINAL_COMMAND_STATUSES) | set(svc._CLAIMABLE_COMMAND_STATUSES)
    control_modes = set(svc._SAFE_CONTROL_MODES)
    algs = {svc.DESKTOP_COMMAND_ENVELOPE_ALGORITHM, svc.DESKTOP_COMMAND_ENVELOPE_ED25519_ALGORITHM}

    claim = _load(CLAIM)
    assert claim["capability"] in capabilities
    assert claim["action"]["name"] in actions
    assert claim["status"] in statuses
    assert claim["control_mode"] in control_modes
    assert claim["envelope"]["schema"] == svc.DESKTOP_COMMAND_ENVELOPE_SCHEMA
    assert claim["envelope"]["signature_alg"] in algs

    for name in (DENY_BUNDLE, DENY_CAP):
        d = _load(name)
        assert d["action"] in actions
        assert d["capability"] in capabilities


# ── P5.3b planner-safe observation delivery contract ─────────────────────

def test_observation_status_fixture_matches_route_model():
    """The status fixture must round-trip through the REAL response model
    (DesktopObservationStatusOut) — any drift between fixture, API model, and
    the Rust PerceptionArtifactStatus mirror fails here or in the CLI test."""
    dc = pytest.importorskip("app.api.v1.desktop_control")
    fixture = _load(OBSERVATION_STATUS)
    out = dc.DesktopObservationStatusOut(**fixture)
    assert out.redaction_status == "planner_safe"
    assert out.redacted_available is True
    assert out.raw_deleted is True
    # storage paths are not part of the contract, at any key
    assert "storage_path" not in fixture
    assert "redacted_storage_path" not in fixture


def test_observation_fetch_denial_code_is_canonical():
    delivery = pytest.importorskip("app.services.perception_delivery")
    fixture = _load(OBSERVATION_FETCH_DENIED)
    detail = fixture["detail"]
    valid = {c.value for c in delivery.PerceptionFetchDenialCode}
    assert detail["code"] in valid
    assert detail["reason"] == detail["reason"].strip()


def test_deny_codes_match_pr_c_enum():
    """Each deny fixture's code is a canonical DesktopDenialCode AND its reason
    maps to that exact code via the PR-C code_for_reason() — real parity, not a
    provisional allow-set (PR-C: apps/api/app/services/desktop_control_codes.py)."""
    codes = pytest.importorskip("app.services.desktop_control_codes")
    valid = {c.value for c in codes.DesktopDenialCode}
    for name in (DENY_BUNDLE, DENY_CAP):
        d = _load(name)
        assert d["code"] in valid, f"{name}: '{d['code']}' is not a DesktopDenialCode"
        assert codes.code_for_reason(d["reason"]).value == d["code"], (
            f"{name}: reason does not map to its code via code_for_reason()"
        )


def test_grant_request_fixture_matches_route_model():
    dc = pytest.importorskip("app.api.v1.desktop_control")
    fixture = _load(GRANT_REQUEST)
    out = dc.DesktopGrantRequestOut(**fixture)
    assert out.status == "pending"
    assert out.grant_present is False
    assert "payload" not in fixture
    assert "storage_path" not in fixture


def test_grant_request_denial_code_is_canonical():
    act = pytest.importorskip("app.services.desktop_act")
    fixture = _load(GRANT_REQUEST_DENIED)
    detail = fixture["detail"]
    valid = {c.value for c in act.DesktopGrantRequestDenialCode}
    assert detail["code"] in valid


def test_grant_approval_fixture_matches_route_model():
    dc = pytest.importorskip("app.api.v1.desktop_control")
    fixture = _load(GRANT_APPROVAL)
    out = dc.DesktopGrantApprovalOut(**fixture)
    assert out.status == "approved"
    assert out.grant_status == "active"
    assert out.risk_tier == "native_control"
    assert out.grant_present is True
    assert "payload" not in fixture
    assert "envelope" not in fixture


def test_actuate_fixture_matches_route_model():
    dc = pytest.importorskip("app.api.v1.desktop_control")
    fixture = _load(ACTUATE)
    out = dc.DesktopActuateOut(**fixture)
    assert out.status == "queued"
    assert out.command_status == "pending"
    assert out.approval_id is not None
    assert "args" not in fixture and "envelope" not in fixture
