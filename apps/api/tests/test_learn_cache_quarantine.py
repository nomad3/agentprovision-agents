"""T3.3 — cache + quarantine helpers + §1.11 mutual-exclusion invariant.

Spec §1.11 + §2 layout:
    _tenant/<uuid>/_learning_cache/<job_id>/{transcript.txt, draft.md,
                                              review.json, test.json}      (7d)
    _tenant/<uuid>/_learning_quarantine/<job_id>/{transcript.txt, draft.md,
                                                  review.json, test_result.json,
                                                  abort_reason.txt}        (30d)

A given ``job_id`` MUST appear in at most one of those locations. The
``CacheAndQuarantineConflict`` exception enforces this invariant on both
write paths (cache check existing quarantine, quarantine checks existing
cache).
"""
from __future__ import annotations

import json

import pytest

from app.workflows.activities.learn_from_media_activities import (
    CacheAndQuarantineConflict,
    _tenant_root,
    act_write_cache,
    act_write_quarantine,
)


def test_tenant_root_resolves(tmp_path, monkeypatch):
    """``_tenant_root`` honours the monkeypatched ``_WORKSPACE_BASE``."""
    monkeypatch.setattr(
        "app.workflows.activities.learn_from_media_activities._WORKSPACE_BASE",
        tmp_path,
    )
    assert _tenant_root("uuid-1") == tmp_path / "_tenant" / "uuid-1"


@pytest.mark.asyncio
async def test_write_quarantine_layout(tmp_path, monkeypatch):
    """Quarantine bundle materialises all expected files at the right path."""
    monkeypatch.setattr(
        "app.workflows.activities.learn_from_media_activities._WORKSPACE_BASE",
        tmp_path,
    )
    job_id = "2026-05-25-123000-fix-printer"
    r = await act_write_quarantine(
        tenant_id="t1",
        job_id=job_id,
        transcript="raw transcript with PII",
        draft={"skill_md": "---\nname: x\n---\nbody"},
        review={"verdict": "rejected"},
        test_result=None,
        abort_reason="rejected by reviewer",
    )
    qdir = tmp_path / "_tenant" / "t1" / "_learning_quarantine" / job_id
    assert r["quarantine_dir"] == str(qdir)
    assert (qdir / "transcript.txt").read_text() == "raw transcript with PII"
    assert (qdir / "draft.md").read_text() == "---\nname: x\n---\nbody"
    assert json.loads((qdir / "review.json").read_text()) == {"verdict": "rejected"}
    assert (qdir / "abort_reason.txt").read_text() == "rejected by reviewer"
    # test_result was None → file should NOT exist
    assert not (qdir / "test_result.json").exists()


@pytest.mark.asyncio
async def test_write_cache_layout(tmp_path, monkeypatch):
    """Cache bundle materialises transcript + draft + optional review/test."""
    monkeypatch.setattr(
        "app.workflows.activities.learn_from_media_activities._WORKSPACE_BASE",
        tmp_path,
    )
    r = await act_write_cache(
        tenant_id="t1",
        job_id="job-1",
        transcript="scrubbed transcript",
        draft={"skill_md": "---\nname: x\n---\nbody"},
        last_review={"verdict": "revise"},
        last_test=None,
    )
    cdir = tmp_path / "_tenant" / "t1" / "_learning_cache" / "job-1"
    assert r["cache_dir"] == str(cdir)
    assert (cdir / "transcript.txt").read_text() == "scrubbed transcript"
    assert (cdir / "draft.md").read_text() == "---\nname: x\n---\nbody"
    assert json.loads((cdir / "review.json").read_text()) == {"verdict": "revise"}
    # last_test was None → file should NOT exist
    assert not (cdir / "test.json").exists()


@pytest.mark.asyncio
async def test_cache_then_quarantine_raises_conflict(tmp_path, monkeypatch):
    """Spec §1.11 invariant, direction 1: cache exists → quarantine refuses."""
    monkeypatch.setattr(
        "app.workflows.activities.learn_from_media_activities._WORKSPACE_BASE",
        tmp_path,
    )
    job_id = "job-mutex-test"
    await act_write_cache(
        tenant_id="t1",
        job_id=job_id,
        transcript="x",
        draft={},
        last_review=None,
        last_test=None,
    )
    with pytest.raises(CacheAndQuarantineConflict):
        await act_write_quarantine(
            tenant_id="t1",
            job_id=job_id,
            transcript="x",
            draft={},
            review={},
            test_result=None,
            abort_reason="x",
        )


@pytest.mark.asyncio
async def test_quarantine_then_cache_raises_conflict(tmp_path, monkeypatch):
    """Spec §1.11 invariant, direction 2: quarantine exists → cache refuses."""
    monkeypatch.setattr(
        "app.workflows.activities.learn_from_media_activities._WORKSPACE_BASE",
        tmp_path,
    )
    job_id = "2026-05-25-090000-job-mutex-test"
    await act_write_quarantine(
        tenant_id="t1",
        job_id=job_id,
        transcript="x",
        draft={},
        review={},
        test_result=None,
        abort_reason="x",
    )
    with pytest.raises(CacheAndQuarantineConflict):
        await act_write_cache(
            tenant_id="t1",
            job_id=job_id,
            transcript="x",
            draft={},
            last_review=None,
            last_test=None,
        )
