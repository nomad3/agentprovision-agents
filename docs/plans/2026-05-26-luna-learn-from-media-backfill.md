# Luna Learn from Media — meta-skill for video → skill synthesis

**Date:** 2026-05-26 · **Status:** Backfilled (shipped)
**PRs:** #726
**Files:** `apps/api/app/skills/_bundled/luna_learn_from_media/skill.md`, `apps/mcp-server/src/mcp_tools/learning.py`, `apps/mcp-server/src/mcp_tools/learning_prompts.py`, `apps/api/app/workflows/learn_from_media_workflow.py`, `apps/api/app/workflows/activities/learn_from_media_activities.py`, `apps/api/app/workflows/learning_audio_cleanup_workflow.py`, `apps/api/app/services/learning_service.py`, `apps/api/app/services/url_intent_router.py`, `apps/api/app/api/v1/learning.py`, `apps/api/app/api/v1/skills_new.py`, `apps/agentprovision-cli/src/commands/learn.rs`, `apps/api/migrations/156_luna_add_learning_tool_group.sql`, `docs/operator/luna-learn-setup.md`

## Problem / context

Skills were only ever authored by a human (Skills v2: `_bundled/` + `_tenant/<uuid>/`, Claude-Code-style `SKILL.md`). There was no path for Luna to *acquire* a new capability from an instructional artifact a user already has — a YouTube tutorial, an Instagram reel, an uploaded screen-recording. PR #726 closes that gap with a **meta-skill**: a skill whose output is itself a runnable, installed skill. The design was co-authored with the Luna agent (`cfb6dd14…`) across 3 brainstorming dispatches plus two spec-reviewer iterations, then shipped as a single large merge (the squash commit `dcf81497`, ~12k additions) carrying the spec, the implementation plan, and the full implementation together.

## What shipped

**Architecture: hybrid (Approach C).** The skill body is a *contract*, not the driver. The bundled meta-skill at `apps/api/app/skills/_bundled/luna_learn_from_media/skill.md` (`engine: markdown`, `category: meta`, `auto_trigger` on learning-verb + media URL/attachment) documents an 8-step pipeline so the flow is legible to Luna and any agent reading her toolkit. The actual orchestration is a **Temporal workflow** — `LearnFromMediaWorkflow` (`apps/api/app/workflows/learn_from_media_workflow.py`). Luna's final review forced this: single-turn LLM chaining of 7 MCP tools routinely blows the 60–90s HTTP gateway timeout, so the driver became "Temporal workflow dispatched by Luna's reasoning, completing across multiple turns" while the MCP-primitive contract stayed unchanged.

**The 7 MCP primitives** live in a new `learning` tool group (`apps/mcp-server/src/mcp_tools/learning.py`), registered in `TOOLS`: `extract_media`, `transcribe_url`, `synthesize_skill_draft`, `dispatch_skill_review`, `run_synthetic_test`, `install_skill`, `diffuse_learning`. The module defines a typed-exception hierarchy (`MediaTooLong→413`, `MediaPrivate→451`, `MediaNotFound→404`, `MediaGeoBlocked→403`, `MediaAntiScrape→429`, `DraftForbiddenShellout→424`, `ReviewerNotProvisioned→503`, `SlugExhausted→409`, …) so Temporal activities branch on `error_type` rather than parsing 500s, and so Luna can tell the user *why* a clip failed in plain language.

**The pipeline** (workflow steps → activities):
1. **extract** — `extract_media` (yt-dlp wrapper) downloads the audio track to `/var/agentprovision/workspaces/_learning/<job_id>.m4a`; rejects upfront over the duration cap (15 min default).
2. **transcribe** — `transcribe_url` hands audio to the existing transcription endpoint; the transcript is the one artifact kept past the audio sweep.
3. **synth** — `synthesize_skill_draft`: one Claude Sonnet call (prompts in `learning_prompts.py`) emits a full `SKILL.md` + a paired synthetic test `{input, expected}`. The prompt defaults to `engine: markdown`, **forbids** `yt-dlp`/`ffmpeg`/`curl`/`wget` shellouts in the skill body, scrubs PII, and generates a kebab-case slug.
4. **review** — `dispatch_skill_review` sends draft+transcript+test to the bundled `code-reviewer` agent → `approved`/`revise`/`rejected`. `revise` loops back to synth with findings as hints (`LUNA_LEARN_MAX_REVISE_RETRIES`, default 2); `rejected` → quarantine; reviewer absent → cache + "review it yourself."
5. **test** — `run_synthetic_test` executes the *uninstalled* draft against the synthetic input via internal `/skills/library/execute-draft` (sandboxed temp copy); fail is treated like `revise`.
6. **install** — `install_skill` writes to `_tenant/<tenant_uuid>/<slug>/skill.md`, registers `skill_registry` (UNIQUE `(tenant_id, slug)` → `SlugExhausted` after a suffix-try loop), and writes a `library_revisions` audit row with the source URL as `reason` (internal `/skills/library/install-learned`).
7. **diffuse** — `diffuse_learning` records a `LearnedSkill` knowledge-graph observation tagged with the draft's capabilities. Because KG observations are **tenant-scoped**, other agents discover the new skill via `find_skill(capability=…)` with no cross-agent plumbing — the "single-agent learning → population-level capability" angle. Diffuse soft-fails: install already succeeded, so a KG-down still returns `success` with `diffuse_cached: true`.
8. **notify** — a `ChatMessage` with `context.kind="learn_complete"` to the originating session; WhatsApp/web/mobile pick it up via existing message-out plumbing.

**How Luna invokes it — three entry points, one dispatch surface** (`LearningService.dispatch` → `start_workflow("LearnFromMediaWorkflow")`):
- **Conversational**: the bundled meta-skill auto-triggers when a user sends a YouTube/`youtu.be`/Instagram URL (or uploads a clip) with an instructional verb; Luna acks immediately and dispatches.
- **WhatsApp inbound**: `_detect_inbound_media` in `whatsapp_service.py` calls `extract_learning_url` (`url_intent_router.py`, regexes for YouTube watch/shorts, youtu.be, Instagram reel/reels/p) and routes matched text to the dispatcher.
- **CLI**: `alpha learn <url>` (`apps/agentprovision-cli/src/commands/learn.rs`) — fire-and-forget, plus `--dry-run`, `--from-attachment FILE`, `--resume <job_id>`, `--resume-last`; POSTs the `LearningIntent` to `/api/v1/learning/dispatch`.

**Resume / cache / quarantine.** Each step persists to a cached `LearningJobState` keyed by `job_id`. Recoverable failures (reviewer-down, KG-down) go to a 7-day resume cache so `alpha learn --resume-last` re-dispatches without re-paying transcription; terminal failures (rejected, test-fail, PII-required) go to 30-day quarantine. Extracted audio under `_learning/` is swept daily at 04:00 UTC (`LearningAudioCleanupWorkflow`, mtime > 24h); transcripts/drafts are kept indefinitely. `act_extract_media` was later given a bounded `retry_policy` (2026-06-01 incident note in the workflow) after the default unlimited-retry was found to hammer an external host.

**Permissions & deps.** Migration `156_luna_add_learning_tool_group.sql` appends `learning` as the 19th tool group on the Luna Supervisor row for Simon's tenant, kept in lockstep with the bundled `luna/skill.md` frontmatter (guarded by `test_luna_learning_tool_group.py`). `yt-dlp` (pip) + `ffmpeg` (apt) were added to the mcp-server image. Operator setup is documented in `docs/operator/luna-learn-setup.md`.

## Outcome

Shipped in PR #726 (merged 2026-05-26, squash `dcf81497`). The meta-skill, 7 MCP primitives, Temporal workflow + activities, audio-cleanup workflow, CLI `alpha learn`, WhatsApp/chat URL routing, and migration 156 all landed together with a large test suite (~25 test files: workflow happy/error paths, PII scrub, cache/quarantine, install-learned, draft-execute, router-startup, WhatsApp integration). Sources at MVP: YouTube + Instagram reels (Simon overrode Luna's YouTube-only pick). Deferred to §8 follow-ups: YouTube OAuth (private/unlisted/age-gated), an Instagram-auth feasibility study (Meta Graph API can't reach arbitrary reels), TikTok, a web UI, cross-tenant diffusion, and `alpha unlearn`.

## Related

- `docs/superpowers/specs/2026-05-25-luna-learn-from-media-design.md` — the ratified spec (8 sections) shipped in this PR
- `docs/superpowers/plans/2026-05-25-luna-learn-from-media-plan.md` — the 25-task / 7-phase implementation plan (task IDs T1.x–T4.x referenced throughout the code)
- `docs/operator/luna-learn-setup.md` — operator runbook (yt-dlp/ffmpeg, tool-group grant)
- `docs/plans/2026-03-12-skills-marketplace-v2-design.md` — the `_bundled/` + `_tenant/<uuid>/` library this skill installs into
- Memory: `skills_marketplace_v2.md` (library layout, `library_revisions` audit), `autonomous_learning_vision.md` (system acquiring capability over time)
