"""LearnFromMediaWorkflow — orchestrates the Luna Learn pipeline (spec §1.10).

T3.2a — happy path: extract (or probe attachment) → transcribe → synth →
review (must be ``approved``) → test (must pass) → install → diffuse
→ notify.

T3.2b — extract-error per-type branches: each yt-dlp typed error
(MediaPrivate/MediaNotFound/MediaGeoBlocked/MediaAntiScrape/MediaTooLong)
maps to a user-facing notify message (per spec §3) + a quarantine write.

T3.2c — review branches: revise loop (max LUNA_LEARN_MAX_REVISE_RETRIES,
default 2) with hints flowed back into synth; rejected → quarantine;
ReviewerNotProvisioned → cache (recoverable) + --resume-last hint;
ReviewTimeout → quarantine (terminal).

T3.2d — test_failed → quarantine + audit row (act_log_test_fail).

T3.2e — diffuse soft-fail: install succeeded, KG observation cached;
status STILL ``success`` with ``diffuse_cached: true`` (don't propagate
soft-fail as failure).

T3.2f — install_failed branches (SlugExhausted, UnknownError) return
``install_failed`` so the workflow surfaces the error envelope to caller;
real DB+FS rollback semantics live server-side in T4.4e.

Note on activity args: ``workflow.execute_activity`` for typed callables
accepts at most one positional ``arg``; multi-param activities MUST be
called with ``args=[...]`` (see temporalio.workflow:2381 multi-param
overload). The plan code's positional-vararg form would crash the
workflow task and Temporal would retry it forever; we use ``args=`` here.
"""
import os
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    import hashlib
    import re

    import yaml

    from app.workflows.activities import learn_from_media_activities as A


def _read_max_revise_retries() -> int:
    """LUNA_LEARN_MAX_REVISE_RETRIES env (default 2 per spec §3)."""
    try:
        return int(os.environ.get("LUNA_LEARN_MAX_REVISE_RETRIES", "2"))
    except (TypeError, ValueError):
        return 2


# Read at module import time. Temporal's workflow sandbox forbids
# ``os.environ`` access from within the workflow body — the value must be
# baked at import time so the workflow stays deterministic. Tests that
# need to override use ``monkeypatch.setattr`` on this module attribute.
_MAX_REVISE_RETRIES = _read_max_revise_retries()


# Spec §3 — per-error-type user-facing notify messages. Keys are the
# typed-error ``error.type`` strings emitted by the MCP shim (T1.2a).
_EXTRACT_ERROR_NOTIFY = {
    "MediaPrivate": (
        "this video requires sign-in or is restricted — Luna can't access it. "
        "If you have permission, download it and re-send with `--from-attachment`."
    ),
    "MediaNotFound": "this video doesn't exist or has been removed.",
    "MediaGeoBlocked": (
        "this video is geo-blocked from Luna's region. "
        "If you can access it, download it and re-send with `--from-attachment`."
    ),
    "MediaAntiScrape": (
        "the platform is rate-limiting or blocking automated access. "
        "Try again later or re-send the file with `--from-attachment`."
    ),
    "MediaTooLong": (
        "this video exceeds the 15-minute cap. Split it into shorter "
        "clips or re-send a trimmed version."
    ),
}


def _extract_notify_message(err: dict) -> str:
    """Map an extract-error envelope to a user-facing notify string."""
    etype = (err or {}).get("type", "UnknownError")
    return _EXTRACT_ERROR_NOTIFY.get(
        etype,
        f"couldn't fetch the media ({etype}). "
        "Try re-sending the file with `--from-attachment`.",
    )


# Per-step timeouts. ``review`` is 70s = MCP-side 60s reviewer gate + 10s
# headroom so the workflow timeout doesn't race the in-shim timeout
# (which would lose the typed ``ReviewTimeout`` envelope).
_ACTIVITY_TIMEOUTS = {
    "extract": timedelta(minutes=5),
    "transcribe": timedelta(minutes=10),
    "synth": timedelta(minutes=2),
    "review": timedelta(seconds=70),
    "test": timedelta(minutes=2),
    "install": timedelta(seconds=30),
    "diffuse": timedelta(seconds=15),
    "notify": timedelta(seconds=15),
    "write": timedelta(seconds=30),
    "probe": timedelta(seconds=30),
}


def _extract_capabilities(skill_md: str) -> list[str]:
    """Pull ``auto_trigger`` + ``tags`` from frontmatter for the KG observation."""
    m = re.match(r"^---\n(.+?)\n---", skill_md, re.DOTALL)
    if not m:
        return []
    fm = yaml.safe_load(m.group(1)) or {}
    return [fm.get("auto_trigger", "").strip()] + list(fm.get("tags") or [])


def _skill_name(skill_md: str) -> str:
    m = re.match(r"^---\n(.+?)\n---", skill_md, re.DOTALL)
    fm = (yaml.safe_load(m.group(1)) if m else {}) or {}
    return fm.get("name", "<unnamed>")


@workflow.defn(name="LearnFromMediaWorkflow")
class LearnFromMediaWorkflow:
    @workflow.run
    async def run(self, intent_dict: dict) -> dict:
        intent = intent_dict  # validated upstream by LearningService (T4.1a)
        source_url = intent.get("source_url")
        attachment = intent.get("attachment_path")
        tenant_id = intent["tenant_id"]
        learned_by = intent["actor_user_id"]
        session_id = intent.get("session_id")

        # --- step 1: extract OR probe attachment ---
        if attachment:
            probe = await workflow.execute_activity(
                A.act_probe_attachment,
                attachment,
                start_to_close_timeout=_ACTIVITY_TIMEOUTS["probe"],
            )
            if not probe["ok"]:
                return {"status": "attachment_invalid", "error": probe["error"]}
            audio_path = attachment
            provenance_url = f"attachment://{attachment.split('/')[-1]}"
        else:
            extract = await workflow.execute_activity(
                A.act_extract_media,
                args=[source_url, 900],
                start_to_close_timeout=_ACTIVITY_TIMEOUTS["extract"],
            )
            if not extract["ok"]:
                # T3.2b — per-error-type notify message + quarantine.
                err = extract["error"] or {}
                notify_message = _extract_notify_message(err)
                await workflow.execute_activity(
                    A.act_write_quarantine,
                    args=[
                        tenant_id,
                        workflow.info().workflow_id,
                        "",  # no transcript yet
                        None,
                        None,
                        None,
                        f"extract_failed: {err.get('type', 'UnknownError')}",
                    ],
                    start_to_close_timeout=_ACTIVITY_TIMEOUTS["write"],
                )
                if session_id:
                    await workflow.execute_activity(
                        A.act_notify_session,
                        args=[session_id, {"status": "extract_failed", "message": notify_message}],
                        start_to_close_timeout=_ACTIVITY_TIMEOUTS["notify"],
                    )
                return {
                    "status": "extract_failed",
                    "error": err,
                    "notify_message": notify_message,
                }
            audio_path = extract["data"]["audio_path"]
            provenance_url = source_url

        # --- step 2: transcribe (deletes audio on success per T3.1) ---
        trans = await workflow.execute_activity(
            A.act_transcribe_url,
            audio_path,
            start_to_close_timeout=_ACTIVITY_TIMEOUTS["transcribe"],
        )
        if not trans["ok"]:
            return {"status": "transcribe_failed", "error": trans["error"]}
        transcript = trans["data"]["transcript"]

        # --- step 3+4: synth → review loop (T3.2c) ---
        # On verdict=revise the reviewer's findings flow into the next synth
        # call as hints. Capped at LUNA_LEARN_MAX_REVISE_RETRIES extra
        # revise attempts (default 2 per spec §3) → revise_exhausted →
        # quarantine. ReviewerNotProvisioned is recoverable (cache + resume
        # hint); ReviewTimeout is terminal (quarantine).
        max_revise = _MAX_REVISE_RETRIES
        hints: list[str] = []
        draft = None
        review = None
        revise_attempts = 0
        # Initial synth (attempt 0) + up to max_revise revisions.
        for attempt in range(max_revise + 1):
            synth = await workflow.execute_activity(
                A.act_synthesize_skill_draft,
                args=[transcript, provenance_url, hints],
                start_to_close_timeout=_ACTIVITY_TIMEOUTS["synth"],
            )
            if not synth["ok"]:
                return {"status": "synth_failed", "error": synth["error"]}
            draft = synth["data"]

            review = await workflow.execute_activity(
                A.act_dispatch_skill_review,
                args=[
                    draft["skill_md"],
                    transcript,
                    provenance_url,
                    draft["synthetic_test_input"],
                    draft["synthetic_test_expected"],
                ],
                start_to_close_timeout=_ACTIVITY_TIMEOUTS["review"],
            )
            if not review["ok"]:
                # Per spec §3:
                #   ReviewerNotProvisioned → cache + --resume-last hint
                #     (recoverable). User can re-trigger after operator
                #     provisions the Code Reviewer agent.
                #   ReviewTimeout → quarantine (terminal). Reviewer agent
                #     exists but didn't respond in 60s; investigating that
                #     is an operator concern, not user-recoverable.
                #   Anything else (UnknownError, etc) → quarantine.
                err = review["error"] or {}
                etype = err.get("type", "UnknownError")
                if etype == "ReviewerNotProvisioned":
                    cache_msg = (
                        "skill review unavailable; ask operator to provision "
                        "the Code Reviewer agent, then re-send the URL or run "
                        "`alpha learn --resume-last` to pick up from review."
                    )
                    await workflow.execute_activity(
                        A.act_write_cache,
                        args=[
                            tenant_id,
                            workflow.info().workflow_id,
                            transcript,
                            draft,
                            None,
                            "reviewer_not_provisioned",
                        ],
                        start_to_close_timeout=_ACTIVITY_TIMEOUTS["write"],
                    )
                    if session_id:
                        await workflow.execute_activity(
                            A.act_notify_session,
                            args=[
                                session_id,
                                {"status": "review_unavailable", "message": cache_msg},
                            ],
                            start_to_close_timeout=_ACTIVITY_TIMEOUTS["notify"],
                        )
                    return {
                        "status": "review_unavailable",
                        "error": err,
                        "notify_message": cache_msg,
                        "cached": True,
                    }
                # ReviewTimeout / anything else → quarantine + terminal.
                quar_msg = (
                    "couldn't get a review verdict in time. The skill was "
                    "quarantined; operator can inspect and re-run."
                    if etype == "ReviewTimeout"
                    else f"review failed ({etype}); skill quarantined."
                )
                await workflow.execute_activity(
                    A.act_write_quarantine,
                    args=[
                        tenant_id,
                        workflow.info().workflow_id,
                        transcript,
                        draft,
                        None,
                        None,
                        f"review_failed: {etype}",
                    ],
                    start_to_close_timeout=_ACTIVITY_TIMEOUTS["write"],
                )
                if session_id:
                    await workflow.execute_activity(
                        A.act_notify_session,
                        args=[
                            session_id,
                            {"status": "review_failed", "message": quar_msg},
                        ],
                        start_to_close_timeout=_ACTIVITY_TIMEOUTS["notify"],
                    )
                return {
                    "status": "review_failed",
                    "error": err,
                    "notify_message": quar_msg,
                }

            verdict = review["data"]["verdict"]
            if verdict == "approved":
                break
            if verdict == "rejected":
                findings = review["data"].get("findings", [])
                reason = "; ".join(findings) if findings else "no reason provided"
                quar_msg = (
                    f"reviewer rejected the skill: {reason}. "
                    "It has been quarantined for operator review."
                )
                await workflow.execute_activity(
                    A.act_write_quarantine,
                    args=[
                        tenant_id,
                        workflow.info().workflow_id,
                        transcript,
                        draft,
                        review["data"],
                        None,
                        f"rejected: {reason}",
                    ],
                    start_to_close_timeout=_ACTIVITY_TIMEOUTS["write"],
                )
                if session_id:
                    await workflow.execute_activity(
                        A.act_notify_session,
                        args=[
                            session_id,
                            {"status": "rejected", "message": quar_msg},
                        ],
                        start_to_close_timeout=_ACTIVITY_TIMEOUTS["notify"],
                    )
                return {
                    "status": "rejected",
                    "findings": findings,
                    "notify_message": quar_msg,
                }
            # verdict == "revise" — loop with reviewer findings as hints,
            # unless we've exhausted the retry budget.
            revise_attempts += 1
            hints = list(review["data"].get("findings", []))
            if attempt == max_revise:
                # Last attempt also came back as ``revise`` → exhausted.
                final = "; ".join(hints) if hints else "no specifics"
                exhausted_msg = (
                    "couldn't refine the skill to passing quality after "
                    f"{revise_attempts} revisions (final issues: {final})."
                )
                await workflow.execute_activity(
                    A.act_write_quarantine,
                    args=[
                        tenant_id,
                        workflow.info().workflow_id,
                        transcript,
                        draft,
                        review["data"],
                        None,
                        f"revise_exhausted: {final}",
                    ],
                    start_to_close_timeout=_ACTIVITY_TIMEOUTS["write"],
                )
                if session_id:
                    await workflow.execute_activity(
                        A.act_notify_session,
                        args=[
                            session_id,
                            {"status": "revise_exhausted", "message": exhausted_msg},
                        ],
                        start_to_close_timeout=_ACTIVITY_TIMEOUTS["notify"],
                    )
                return {
                    "status": "revise_exhausted",
                    "findings": hints,
                    "notify_message": exhausted_msg,
                    "revise_attempts": revise_attempts,
                }

        # --- step 5: synthetic test ---
        test = await workflow.execute_activity(
            A.act_run_synthetic_test,
            args=[
                draft["skill_md"],
                draft["synthetic_test_input"],
                draft["synthetic_test_expected"],
            ],
            start_to_close_timeout=_ACTIVITY_TIMEOUTS["test"],
        )
        if not test["ok"] or not test["data"]["passed"]:
            return {
                "status": "test_failed",
                "error": test["data"].get("error") if test["ok"] else test["error"],
            }

        # --- step 6: install ---
        sha256 = hashlib.sha256(transcript.encode()).hexdigest()
        install = await workflow.execute_activity(
            A.act_install_skill,
            args=[
                draft["skill_md"],
                draft["slug"],
                tenant_id,
                provenance_url,
                review["data"]["reviewer_agent_id"],
                sha256,
                learned_by,
            ],
            start_to_close_timeout=_ACTIVITY_TIMEOUTS["install"],
        )
        if not install["ok"]:
            return {"status": "install_failed", "error": install["error"]}

        # --- step 7: diffuse (soft-fail handled in T3.2e) ---
        capabilities = _extract_capabilities(draft["skill_md"])
        await workflow.execute_activity(
            A.act_diffuse_learning,
            args=[install["data"]["skill_id"], provenance_url, capabilities],
            start_to_close_timeout=_ACTIVITY_TIMEOUTS["diffuse"],
        )

        # --- step 8: notify ---
        result = {
            "status": "success",
            "skill_id": install["data"]["skill_id"],
            "skill_path": install["data"]["path"],
            "skill_name": _skill_name(draft["skill_md"]),
            "capabilities": capabilities,
            "source_url": provenance_url,
        }
        if session_id:
            await workflow.execute_activity(
                A.act_notify_session,
                args=[session_id, result],
                start_to_close_timeout=_ACTIVITY_TIMEOUTS["notify"],
            )
        return result
