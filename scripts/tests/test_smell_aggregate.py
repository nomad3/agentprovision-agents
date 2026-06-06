from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "smell_aggregate", ROOT / "scripts" / "smell" / "aggregate.py"
)
smell_aggregate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(smell_aggregate)


def test_fail_loud_rejects_degraded_preflight(capsys):
    payload = {
        "preflight": {
            "exit_summary": "degraded",
            "commands_attempted": [{"cmd": "docker ps", "exit": 0, "lines": 3}],
        },
        "findings": [],
    }

    with pytest.raises(SystemExit) as exc:
        smell_aggregate.fail_loud("errors", payload)

    assert exc.value.code == 2
    assert "reported degraded preflight" in capsys.readouterr().err


def test_fail_loud_allows_empty_findings_with_successful_preflight():
    payload = {
        "preflight": {
            "exit_summary": "ok",
            "commands_attempted": [{"cmd": "node scripts/smell/unrouted_pages.js", "exit": 0}],
        },
        "findings": [],
    }

    smell_aggregate.fail_loud("dead_code", payload)


def test_fail_loud_rejects_empty_findings_without_preflight_evidence(capsys):
    payload = {
        "preflight": {"exit_summary": "ok", "commands_attempted": []},
        "findings": [],
    }

    with pytest.raises(SystemExit) as exc:
        smell_aggregate.fail_loud("hotspots", payload)

    assert exc.value.code == 2
    assert "ZERO findings AND no preflight evidence" in capsys.readouterr().err
