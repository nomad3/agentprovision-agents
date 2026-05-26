---
name: Luna Learn from Media
engine: markdown
category: meta
tags: [learning, video, transcription, knowledge, meta]
auto_trigger: "When the user sends a YouTube/Instagram/short-form video URL or asks you to 'learn this', 'study this clip', 'turn this into a skill', or otherwise convert media into an installable capability."
inputs:
  - name: source_url
    type: string
    description: "URL of the media (YouTube, youtu.be, Instagram reel/post). Optional if attachment_path supplied."
    required: false
  - name: attachment_path
    type: string
    description: "Local path to an uploaded audio/video file. Optional if source_url supplied."
    required: false
  - name: resume_job_id
    type: string
    description: "Cached job_id to resume an interrupted learning run (re-uses transcript + last draft)."
    required: false
  - name: dry_run
    type: boolean
    description: "When true, run the synthesis pipeline but skip install + diffusion."
    required: false
---

# Luna Learn from Media — orchestration template

This is Luna's "how I learn" reference. When the user hands me a video link (or asks me
to study an uploaded clip), I dispatch the `LearnFromMediaWorkflow` Temporal workflow
and stay in the conversation while it runs. The workflow runs as 8 discrete steps so
that any single step can fail and resume cleanly without re-doing the expensive
transcription pass.

The actual orchestration is a Temporal workflow — this skill body is the contract that
makes the pipeline legible to me and to any other agent reading my toolkit.

## When to trigger

I run this skill (i.e. dispatch the workflow) when one of these is true:

- The user pastes a YouTube / `youtu.be` / Instagram reel/post URL with an
  instructional verb ("learn this", "study this", "turn this into a skill",
  "make a skill out of this", "I want you to know how to do this").
- The user uploads a video/audio attachment with a similar instructional prompt.
- The user explicitly invokes `alpha learn <url>` from the CLI (the CLI calls the
  same workflow entry-point; I don't need to do anything for that case).
- The user replies "resume" to a paused-mid-flight learning thread (I pass
  `resume_job_id` from the cached job state).

I do NOT trigger on bare URLs without an instructional verb — that's just sharing,
not a learn request. When ambiguous, I ask once: "want me to learn from this clip?"

## The 8-step pipeline (what the workflow actually does)

I describe the steps here at a conceptual level so I can mentally model the flow
and answer user questions about where their job is. The implementation lives in
the workflow + activities, not in this skill.

1. **extract** — `extract_media` (yt-dlp wrapper). Downloads the audio track to
   `/var/agentprovision/workspaces/_learning/<job_id>.m4a`. Rejects upfront if
   the source is longer than the configured cap (15 min default). Maps remote
   failures to typed errors (`MediaPrivate`, `MediaGeoBlocked`, `MediaNotFound`,
   `MediaAntiScrape`, `MediaTooLong`) so I can tell the user *why* a clip failed
   in plain language instead of dumping a stack trace.

2. **transcribe** — `transcribe_url`. Hands the extracted audio to the existing
   transcription endpoint. Returns `{transcript, duration_ms, engine}`. The
   transcript is the only artifact persisted past the audio cleanup sweep — if
   the user later asks "what did that video say?" I can recall it from cache.

3. **synth** — `synthesize_skill_draft`. One Claude Sonnet call that ingests the
   transcript and emits a complete SKILL.md (frontmatter + body) plus a paired
   synthetic test (`{input, expected}`). The synthesis prompt:
   - Defaults to `engine: markdown` and only emits `engine: python` when the
     skill is a deterministic computation with clear inputs and outputs.
   - **Forbids** shellouts to `yt-dlp` / `ffmpeg` / `curl` / `wget` inside the
     skill body. External I/O goes through MCP tools, not skill-embedded
     subprocess calls.
   - Scrubs PII (names, addresses, phone numbers, emails, account strings) and
     replaces them with placeholders.
   - Generates a kebab-case slug from the skill name.

4. **review** — `dispatch_skill_review`. Hands the draft + transcript + synthetic
   test to the bundled Code Reviewer agent (`code-reviewer`). The reviewer returns
   one of `approved`, `revise`, `rejected` with structured findings. On `revise`
   I loop back to step 3 with the findings as `hints`, up to
   `LUNA_LEARN_MAX_REVISE_RETRIES` (default 2). On `rejected` I quarantine the
   draft and notify the user — no install. If the reviewer is not provisioned in
   this tenant, the workflow caches the draft to `_quarantine` and tells the
   user "I synthesized a draft but couldn't get peer review here — review it
   yourself with `alpha learn review <job_id>`."

5. **test** — `run_synthetic_test`. Executes the approved draft against the
   synthetic input via the internal `/skills/library/execute-draft` endpoint
   (the draft is not yet installed — execution happens against a sandboxed
   temp copy). Compares actual output against `expected` with subset matching.
   On fail I treat it the same as a `revise` verdict and loop back, capped by
   the same retry budget.

6. **install** — `install_skill`. Writes the SKILL.md into the tenant library at
   `_tenant/<tenant_uuid>/<slug>/skill.md`, registers the row in `skill_registry`
   (UNIQUE constraint on `(tenant_id, slug)` — slug collisions raise
   `SlugExhausted` after a small suffix-try loop), and creates a
   `library_revisions` audit row attributing the install to me with the source
   URL as the `reason`.

7. **diffuse** — `diffuse_learning`. Creates a `LearnedSkill` knowledge-graph
   observation tagged with the capability list from the draft so other agents
   doing `find_skill(capability=...)` can discover it without me having to
   announce it. This is how the learning spreads across the tenant's agent
   roster.

8. **notify** — I post a ChatMessage with `context.kind="learn_complete"` to the
   originating session. WhatsApp / web / mobile clients pick it up through the
   existing message-out plumbing and surface a short success line: "I learned
   `<skill-name>` from that clip — it's installed and ready to use."

## Cache + resume semantics

Every step persists its output to a cached `LearningJobState` keyed by `job_id`.
That gives me three useful properties:

- **Mid-flight crashes recover cleanly.** If the api restarts during step 4 the
  workflow's next attempt re-reads the cached transcript + draft instead of
  re-paying the transcription cost.
- **`alpha learn --resume-last` works.** The CLI grabs the most recent cached
  `job_id` for the actor and re-dispatches with `resume_job_id` set.
- **The user can iterate.** If the install lands but the user wants the body
  tweaked, they can `alpha learn revise <job_id> "add a step for X"` and I'll
  re-enter the loop at step 3 with their hint folded into the prompt.

Audio files in `/var/agentprovision/workspaces/_learning/` are swept by a daily
cron (4:00 UTC) — anything older than 24h goes. Transcripts and drafts in the
`LearningJobState` table are kept indefinitely so users can always recall what
they taught me from which clip.

## What I tell the user during the run

The workflow can take 60–180 s end-to-end (most of that is transcription +
the synthesis LLM call). I acknowledge immediately so they're not staring at a
silent thread:

> "On it — pulling the audio now. I'll ping you when the skill's ready (usually
> a couple of minutes)."

I do not stream per-step progress for short runs — that's noise. For runs that
cross 5 minutes (long clip, retries) I post a single mid-run status:

> "Still going — synthesis took a couple of revisions but the draft's in code
> review now."

When the workflow finishes I deliver the result in one message: skill name, what
it does, where it's installed, and one example invocation the user can copy.

## Failure modes I surface honestly

If any step fails terminally I tell the user *why* in plain language, with the
recovery action they can take:

- `MediaPrivate` → "That clip is private — I can't see it. Could you upload it
  directly instead?"
- `MediaGeoBlocked` → "YouTube is blocking that video for our region — try a
  mirror or send the file."
- `MediaTooLong` → "That's longer than the 15-minute cap I have for learning
  clips. Want to send a shorter excerpt?"
- `DraftForbiddenShellout` after max retries → "I couldn't synthesize a clean
  draft from that clip — every attempt kept reaching for `yt-dlp` or `ffmpeg`
  shellouts I'm not allowed to install. Want me to try with a hint about what
  the skill should actually do?"
- `ReviewerNotProvisioned` → "I made a draft but the code-reviewer isn't set
  up on this tenant. Review it with `alpha learn review <job_id>` and I'll
  install it on your approval."
- `SlugExhausted` → "There are already several skills with that name on your
  tenant — give me a more distinctive name?"

I never silently swallow a failure. Honest failure beats a confident "done!" on
a skill that never installed.
