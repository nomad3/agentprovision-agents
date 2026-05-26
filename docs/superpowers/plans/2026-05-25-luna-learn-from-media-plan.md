# Luna Learn from Media Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Luna Learn meta-skill: user sends a YouTube/IG link → Luna transcribes → synthesizes a SKILL.md → cross-agent code-review → synthetic test → install into tenant library → KG diffusion. Spec: [`docs/superpowers/specs/2026-05-25-luna-learn-from-media-design.md`](../specs/2026-05-25-luna-learn-from-media-design.md).

**Architecture:** Hybrid (Approach C). 7 new MCP primitives in a `learning` tool group execute under a Temporal Dynamic Workflow `LearnFromMediaWorkflow`. Luna's chat turn dispatches the workflow + ACKs the user; workflow runs async; completion notifies back via chat. New `alpha learn` CLI + WhatsApp URL trigger as entry points. New bundled `_bundled/luna_learn_from_media/skill.md` is the orchestration template Luna reads.

**Tech Stack:** Python (`yt-dlp`, `ffmpeg`, FastAPI), Temporal workflows (existing pattern in `apps/api/app/workflows/`), PostgreSQL (existing `skill_registry` table — UNIQUE constraint already at migration 043), Rust CLI (`apps/agentprovision-cli/`), MCP server (`apps/mcp-server/`), Anthropic Claude Sonnet for synthesis.

**PR strategy:** Per `feedback_chain_pr_branches` + `feedback_single_pr_for_feature`: chained sub-branches off `spec/luna-learn-from-media`, one per phase. All squashed-merge as a single PR after final review (avoids N build storms on the single Mac runner per `feedback_single_pr_for_feature`).

---

## §0 — Resolutions to spec §7 open questions

- **LLM model tier for `synthesize_skill_draft`**: Claude Sonnet (full tier). Skill synthesis is high-stakes (we generate installable code). Configurable via env var `LUNA_LEARN_SYNTHESIS_MODEL` defaulting to `claude-sonnet-4-6`.
- **Max revise retries**: 2 per spec. Configurable via env var `LUNA_LEARN_MAX_REVISE_RETRIES` defaulting to `2`.
- **WhatsApp URL regex**: enumerated in T4.2 below. YouTube + youtu.be + IG reel/p variants.
- **UNIQUE(tenant_id, slug) constraint**: ✅ VERIFIED EXISTS — `apps/api/migrations/043_add_skill_registry.sql:19` (`uq_skill_registry_slug_tenant UNIQUE (slug, tenant_id)`). No migration needed.
- **yt-dlp + ffmpeg in code-worker image**: NO. Synthesis prompt forbids skill-embedded shellouts to these tools. Verified by T2.3 unit test (synthesis output must not reference `yt-dlp` or `ffmpeg`).

## §0b — Spec accuracy corrections (to apply during impl)

- Spec says `apps/api/app/agents/luna/AGENT.md` for Luna agent config. Actual path is `apps/api/app/agents/_bundled/luna/skill.md`. Luna currently has NO `tool_groups` frontmatter (the field exists for other agents). T5.2 adds it.

## File structure

**New files:**

| Path | Responsibility |
|---|---|
| `apps/mcp-server/src/mcp_tools/learning.py` | 7 MCP primitive implementations |
| `apps/mcp-server/tests/test_learning.py` | Unit tests for 7 primitives |
| `apps/api/app/schemas/learning.py` | Pydantic models: `LearningIntent`, `SkillDraft`, `ReviewResult`, `TestResult`, `LearningJobState` |
| `apps/api/app/services/learning_service.py` | Service layer: dispatches workflow from CLI/WhatsApp/chat entry points; handles cache/quarantine paths |
| `apps/api/app/workflows/learn_from_media_workflow.py` | Temporal Dynamic Workflow `LearnFromMediaWorkflow` |
| `apps/api/app/workflows/activities/learn_from_media_activities.py` | Temporal activities (one per MCP primitive + cache/quarantine writes) |
| `apps/api/tests/test_luna_learn_integration.py` | End-to-end integration test |
| `apps/agentprovision-cli/src/commands/learn.rs` | `alpha learn` CLI command |
| `apps/agentprovision-cli/src/commands/learn_test.rs` | CLI unit tests |
| `apps/api/app/skills/_bundled/luna_learn_from_media/skill.md` | Orchestration template (Luna reads this) |
| `apps/api/app/services/url_intent_router.py` | URL pattern detection + intent routing helper |

**Modified files:**

| Path | What changes |
|---|---|
| `apps/api/app/services/whatsapp_service.py:_detect_inbound_media` | Add URL detection + learning-intent dispatch |
| `apps/api/app/agents/_bundled/luna/skill.md` | Add `tool_groups: [..., learning]` frontmatter |
| `apps/mcp-server/Dockerfile` | Add `yt-dlp` (pip) + `ffmpeg` (apt) |
| `apps/api/app/workflows/__init__.py` | Register `LearnFromMediaWorkflow` + activities |
| `apps/mcp-server/src/mcp_tools/__init__.py` | Register `learning` module |
| `apps/api/app/services/cron_jobs.py` (or wherever cron lives) | Add `0 4 * * *` audio cleanup sweep |

---

## Phase 0 — Prerequisites

### Task 0.1: Add yt-dlp + ffmpeg to mcp-server image

**Files:**
- Modify: `apps/mcp-server/Dockerfile`

- [ ] **Step 1: Read current Dockerfile**

Run: `cat apps/mcp-server/Dockerfile`
Expected: a `FROM python:...` Dockerfile with `pip install` and apt steps.

- [ ] **Step 2: Add ffmpeg to apt step + yt-dlp to pip step**

Edit `apps/mcp-server/Dockerfile`:
- Find the `RUN apt-get update && apt-get install -y` block; add `ffmpeg` to the package list (alphabetical order if existing).
- Find the `RUN pip install` block (or `requirements.txt`); add `yt-dlp` (pin to `>=2024.10.0` for current IG/YT extractor support).

- [ ] **Step 3: Local sanity build**

Run: `docker build -t mcp-server-test apps/mcp-server/ 2>&1 | tail -20`
Expected: build succeeds; final image contains both binaries.

- [ ] **Step 4: Verify binaries inside container**

Run: `docker run --rm mcp-server-test bash -c "which yt-dlp && which ffmpeg && yt-dlp --version && ffmpeg -version | head -1"`
Expected: both paths print, versions print without error.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t01-deps spec/luna-learn-from-media
git add apps/mcp-server/Dockerfile
git commit -m "deps(mcp-server): add yt-dlp + ffmpeg for Luna Learn"
git push -u origin impl/luna-learn-t01-deps
```

---

## Phase 1 — Schemas + skeletons

### Task 1.1: Pydantic schemas for the learning subsystem

**Files:**
- Create: `apps/api/app/schemas/learning.py`
- Test: `apps/api/tests/test_schema_learning.py` (new)

- [ ] **Step 1: Write failing tests**

Create `apps/api/tests/test_schema_learning.py`:
```python
import pytest
from app.schemas.learning import (
    LearningIntent, SkillDraft, ReviewVerdict, ReviewResult,
    TestResult, LearningJobState,
)

def test_learning_intent_url():
    intent = LearningIntent(source_url="https://youtu.be/abc123", tenant_id="t1", actor_user_id="u1")
    assert intent.source_url == "https://youtu.be/abc123"

def test_learning_intent_attachment():
    intent = LearningIntent(attachment_path="/tmp/x.mp4", tenant_id="t1", actor_user_id="u1")
    assert intent.attachment_path == "/tmp/x.mp4"

def test_learning_intent_requires_url_or_attachment():
    with pytest.raises(ValueError):
        LearningIntent(tenant_id="t1", actor_user_id="u1")

def test_skill_draft_has_test_payload():
    d = SkillDraft(
        skill_md="---\nname: foo\nengine: markdown\n---\nbody",
        slug="foo", engine="markdown",
        synthetic_test_input={"x": 1}, synthetic_test_expected={"y": 2},
    )
    assert d.engine == "markdown"

def test_review_verdict_values():
    assert {ReviewVerdict.APPROVED, ReviewVerdict.REVISE, ReviewVerdict.REJECTED}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && pytest tests/test_schema_learning.py -v`
Expected: FAIL with "No module named 'app.schemas.learning'"

- [ ] **Step 3: Write minimal implementation**

Create `apps/api/app/schemas/learning.py`:
```python
"""Pydantic models for Luna Learn from Media subsystem."""
from __future__ import annotations
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class LearningIntent(BaseModel):
    """A request to learn from media. Either source_url or attachment_path required."""
    source_url: str | None = None
    attachment_path: str | None = None
    tenant_id: str
    actor_user_id: str
    resume_job_id: str | None = None
    dry_run: bool = False

    @model_validator(mode="after")
    def _one_of_url_or_attachment(self) -> "LearningIntent":
        if not self.source_url and not self.attachment_path and not self.resume_job_id:
            raise ValueError("source_url, attachment_path, or resume_job_id required")
        return self


class SkillDraft(BaseModel):
    skill_md: str
    slug: str
    engine: str
    synthetic_test_input: dict
    synthetic_test_expected: dict


class ReviewVerdict(str, Enum):
    APPROVED = "approved"
    REVISE = "revise"
    REJECTED = "rejected"


class ReviewResult(BaseModel):
    verdict: ReviewVerdict
    findings: list[str] = Field(default_factory=list)
    reviewer_agent_id: str


class TestResult(BaseModel):
    passed: bool
    actual_output: dict | None = None
    error: str | None = None


class LearningJobState(BaseModel):
    """Persisted cache state for --resume-last."""
    job_id: str
    source_url: str | None
    transcript: str | None = None
    draft: SkillDraft | None = None
    last_review: ReviewResult | None = None
    last_test: TestResult | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && pytest tests/test_schema_learning.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t11-schemas impl/luna-learn-t01-deps
git add apps/api/app/schemas/learning.py apps/api/tests/test_schema_learning.py
git commit -m "feat(luna-learn): pydantic schemas for learning subsystem"
git push -u origin impl/luna-learn-t11-schemas
```

### Task 1.2: MCP tool group skeleton

**Files:**
- Create: `apps/mcp-server/src/mcp_tools/learning.py`
- Modify: `apps/mcp-server/src/mcp_tools/__init__.py`
- Test: `apps/mcp-server/tests/test_learning.py` (new)

- [ ] **Step 1: Write failing test for tool registration**

Create `apps/mcp-server/tests/test_learning.py`:
```python
import pytest
from mcp_tools import learning

def test_learning_module_exports_7_tools():
    expected = {
        "extract_media", "transcribe_url", "synthesize_skill_draft",
        "dispatch_skill_review", "run_synthetic_test", "install_skill",
        "diffuse_learning",
    }
    assert set(learning.TOOLS.keys()) == expected

@pytest.mark.parametrize("tool", [
    "extract_media", "transcribe_url", "synthesize_skill_draft",
    "dispatch_skill_review", "run_synthetic_test", "install_skill",
    "diffuse_learning",
])
def test_each_tool_callable(tool):
    assert callable(learning.TOOLS[tool])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v`
Expected: FAIL with "No module named 'mcp_tools.learning'"

- [ ] **Step 3: Write minimal skeleton**

Create `apps/mcp-server/src/mcp_tools/learning.py`:
```python
"""Luna Learn — MCP primitives for the meta-skill (spec §1.1)."""
from __future__ import annotations
from typing import Callable


async def extract_media(url: str, max_duration_s: int = 900) -> dict:
    raise NotImplementedError("T2.1")


async def transcribe_url(audio_path: str) -> dict:
    raise NotImplementedError("T2.2")


async def synthesize_skill_draft(transcript: str, source_url: str, hints: list[str] | None = None) -> dict:
    raise NotImplementedError("T2.3")


async def dispatch_skill_review(
    skill_md: str, transcript: str, source_url: str,
    synthetic_test_input: dict, synthetic_test_expected: dict,
) -> dict:
    raise NotImplementedError("T2.4")


async def run_synthetic_test(skill_md: str, test_input: dict, test_expected: dict) -> dict:
    raise NotImplementedError("T2.5")


async def install_skill(
    skill_md: str, slug: str, tenant_id: str,
    source_url: str, reviewer_agent_id: str,
    transcript_sha256: str, learned_by_agent_id: str,
) -> dict:
    raise NotImplementedError("T2.6")


async def diffuse_learning(skill_id: str, source_url: str, capabilities: list[str]) -> dict:
    raise NotImplementedError("T2.7")


TOOLS: dict[str, Callable] = {
    "extract_media": extract_media,
    "transcribe_url": transcribe_url,
    "synthesize_skill_draft": synthesize_skill_draft,
    "dispatch_skill_review": dispatch_skill_review,
    "run_synthetic_test": run_synthetic_test,
    "install_skill": install_skill,
    "diffuse_learning": diffuse_learning,
}
```

Update `apps/mcp-server/src/mcp_tools/__init__.py` to import `learning` (follow the existing pattern of how `skills`/`knowledge` are imported).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v`
Expected: 8 passed (1 export check + 7 callable checks).

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t12-skeleton impl/luna-learn-t11-schemas
git add apps/mcp-server/src/mcp_tools/learning.py apps/mcp-server/src/mcp_tools/__init__.py apps/mcp-server/tests/test_learning.py
git commit -m "feat(luna-learn): MCP tool group skeleton (7 NotImplementedError stubs)"
git push -u origin impl/luna-learn-t12-skeleton
```

### Task 1.3: Temporal workflow skeleton

**Files:**
- Create: `apps/api/app/workflows/learn_from_media_workflow.py`
- Create: `apps/api/app/workflows/activities/learn_from_media_activities.py`
- Modify: `apps/api/app/workflows/__init__.py`

- [ ] **Step 1: Write failing test**

Create `apps/api/tests/test_learn_from_media_workflow_skeleton.py`:
```python
def test_workflow_registered():
    from app.workflows import learn_from_media_workflow as w
    assert hasattr(w, "LearnFromMediaWorkflow")

def test_activities_registered():
    from app.workflows.activities import learn_from_media_activities as a
    expected = {
        "act_extract_media", "act_transcribe_url",
        "act_synthesize_skill_draft", "act_dispatch_skill_review",
        "act_run_synthetic_test", "act_install_skill",
        "act_diffuse_learning",
    }
    actual = {n for n in dir(a) if n.startswith("act_")}
    assert expected.issubset(actual)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && pytest tests/test_learn_from_media_workflow_skeleton.py -v`
Expected: FAIL with import errors.

- [ ] **Step 3: Create skeletons matching existing Temporal pattern**

Reference an existing workflow (e.g. `apps/api/app/workflows/coalition_workflow.py`) for the import shape + `@workflow.defn` + `@activity.defn` decorators.

Create `apps/api/app/workflows/activities/learn_from_media_activities.py`:
```python
"""Temporal activities for LearnFromMediaWorkflow (spec §1.10)."""
from temporalio import activity


@activity.defn
async def act_extract_media(url: str, max_duration_s: int = 900) -> dict:
    raise NotImplementedError("T3.1")


@activity.defn
async def act_transcribe_url(audio_path: str) -> dict:
    raise NotImplementedError("T3.1")


@activity.defn
async def act_synthesize_skill_draft(transcript: str, source_url: str, hints: list[str] | None = None) -> dict:
    raise NotImplementedError("T3.1")


@activity.defn
async def act_dispatch_skill_review(*args, **kwargs) -> dict:
    raise NotImplementedError("T3.1")


@activity.defn
async def act_run_synthetic_test(*args, **kwargs) -> dict:
    raise NotImplementedError("T3.1")


@activity.defn
async def act_install_skill(*args, **kwargs) -> dict:
    raise NotImplementedError("T3.1")


@activity.defn
async def act_diffuse_learning(*args, **kwargs) -> dict:
    raise NotImplementedError("T3.1")
```

Create `apps/api/app/workflows/learn_from_media_workflow.py`:
```python
"""LearnFromMediaWorkflow — orchestrates the Luna Learn pipeline (spec §1.10)."""
from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.workflows.activities import learn_from_media_activities as A


@workflow.defn(name="LearnFromMediaWorkflow")
class LearnFromMediaWorkflow:
    @workflow.run
    async def run(self, intent_dict: dict) -> dict:
        # T3.2 implements the actual orchestration body.
        raise NotImplementedError("T3.2")
```

Register in `apps/api/app/workflows/__init__.py` (follow existing pattern).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/api && pytest tests/test_learn_from_media_workflow_skeleton.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t13-workflow-skeleton impl/luna-learn-t12-skeleton
git add apps/api/app/workflows/learn_from_media_workflow.py apps/api/app/workflows/activities/learn_from_media_activities.py apps/api/app/workflows/__init__.py apps/api/tests/test_learn_from_media_workflow_skeleton.py
git commit -m "feat(luna-learn): Temporal workflow + activities skeleton"
git push -u origin impl/luna-learn-t13-workflow-skeleton
```

---

## Phase 2 — MCP primitive implementations (one task per primitive, TDD)

> Each Phase-2 task branches off the previous (impl/luna-learn-t12-skeleton → t21 → t22 → ...). Final squash-merge after Phase 7 review.

### Task 2.1: `extract_media` — yt-dlp wrapper

**Files:**
- Modify: `apps/mcp-server/src/mcp_tools/learning.py`
- Test: `apps/mcp-server/tests/test_learning.py`

**Behavior contract (from spec §1.1 + §3):**
- Calls `yt-dlp -x --audio-format m4a -o <path> <url>` via subprocess
- Rejects upfront if probed duration > `max_duration_s`
- Maps yt-dlp errors to typed exceptions: `MediaPrivate`, `MediaNotFound`, `MediaGeoBlocked`, `MediaAntiScrape`, `MediaTooLong`, `MediaUnknownError`
- Writes audio to `/var/agentprovision/workspaces/_learning/<job_id>.audio`
- Returns `{audio_path, metadata: {title, duration_s, uploader, source_platform}}`

- [ ] **Step 1: Write failing tests** (cover happy path + each typed exception)

```python
# In apps/mcp-server/tests/test_learning.py, append:
import pytest
from unittest.mock import patch, MagicMock
from mcp_tools.learning import (
    extract_media, MediaPrivate, MediaNotFound, MediaGeoBlocked,
    MediaAntiScrape, MediaTooLong,
)

@pytest.mark.asyncio
async def test_extract_media_happy_path(tmp_path):
    with patch("mcp_tools.learning._run_yt_dlp") as mock_run:
        mock_run.return_value = {
            "title": "Demo", "duration": 90,
            "uploader": "Acme", "extractor": "youtube",
            "_filename": str(tmp_path / "abc.m4a"),
        }
        result = await extract_media("https://youtu.be/abc123")
        assert result["metadata"]["duration_s"] == 90
        assert result["metadata"]["source_platform"] == "youtube"

@pytest.mark.asyncio
async def test_extract_media_too_long():
    with patch("mcp_tools.learning._probe_duration") as p:
        p.return_value = 1200  # 20 min > 900
        with pytest.raises(MediaTooLong):
            await extract_media("https://youtu.be/abc123", max_duration_s=900)

@pytest.mark.asyncio
@pytest.mark.parametrize("stderr,exc", [
    ("Private video", MediaPrivate),
    ("Video unavailable", MediaNotFound),
    ("This video is not available in your country", MediaGeoBlocked),
    ("HTTP Error 429", MediaAntiScrape),
])
async def test_extract_media_error_mapping(stderr, exc):
    with patch("mcp_tools.learning._run_yt_dlp") as r:
        r.side_effect = RuntimeError(stderr)
        with pytest.raises(exc):
            await extract_media("https://example.com/x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k extract_media`
Expected: FAIL with import / NotImplementedError errors.

- [ ] **Step 3: Implement `extract_media` with helpers `_run_yt_dlp` + `_probe_duration` + typed exceptions**

In `apps/mcp-server/src/mcp_tools/learning.py`:
```python
import asyncio
import os
import shutil
import uuid
from pathlib import Path

_LEARNING_DIR = Path("/var/agentprovision/workspaces/_learning")


class MediaError(Exception): ...
class MediaPrivate(MediaError): ...
class MediaNotFound(MediaError): ...
class MediaGeoBlocked(MediaError): ...
class MediaAntiScrape(MediaError): ...
class MediaTooLong(MediaError): ...


async def _probe_duration(url: str) -> int:
    """yt-dlp --get-duration <url> → seconds."""
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", "--get-duration", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode() or "yt-dlp probe failed")
    # Format: "HH:MM:SS" or "MM:SS"; convert to seconds.
    parts = out.decode().strip().split(":")
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs


async def _run_yt_dlp(url: str, output_path: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", "-x", "--audio-format", "m4a",
        "-o", output_path, "--print-json", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode() or "yt-dlp failed")
    import json
    return json.loads(out.decode().splitlines()[-1])


def _map_ytdlp_error(stderr: str) -> type[MediaError]:
    s = stderr.lower()
    if "private" in s or "sign in" in s or "age" in s:
        return MediaPrivate
    if "unavailable" in s or "removed" in s or "404" in s:
        return MediaNotFound
    if "not available in your country" in s or "geo" in s:
        return MediaGeoBlocked
    if "429" in s or "rate" in s or "blocked" in s:
        return MediaAntiScrape
    return MediaError


async def extract_media(url: str, max_duration_s: int = 900) -> dict:
    """Spec §1.1 extract_media."""
    _LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    job_id = uuid.uuid4().hex
    output_path = str(_LEARNING_DIR / f"{job_id}.%(ext)s")
    try:
        dur = await _probe_duration(url)
    except RuntimeError as e:
        raise _map_ytdlp_error(str(e))(str(e)) from e
    if dur > max_duration_s:
        raise MediaTooLong(f"duration {dur}s exceeds cap {max_duration_s}s")
    try:
        meta = await _run_yt_dlp(url, output_path)
    except RuntimeError as e:
        raise _map_ytdlp_error(str(e))(str(e)) from e
    return {
        "audio_path": meta.get("_filename") or str(_LEARNING_DIR / f"{job_id}.m4a"),
        "metadata": {
            "title": meta.get("title"),
            "duration_s": meta.get("duration"),
            "uploader": meta.get("uploader"),
            "source_platform": meta.get("extractor"),
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k extract_media`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t21-extract-media impl/luna-learn-t13-workflow-skeleton
git add apps/mcp-server/src/mcp_tools/learning.py apps/mcp-server/tests/test_learning.py
git commit -m "feat(luna-learn): extract_media — yt-dlp wrapper with typed errors + duration cap"
git push -u origin impl/luna-learn-t21-extract-media
```

### Task 2.2: `transcribe_url` — wrap existing transcription client

**Files:**
- Modify: `apps/mcp-server/src/mcp_tools/learning.py`
- Test: `apps/mcp-server/tests/test_learning.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_transcribe_url_calls_existing_client(tmp_path):
    audio = tmp_path / "x.m4a"; audio.write_bytes(b"\x00" * 100)
    with patch("mcp_tools.learning._transcribe_bytes_async") as t:
        t.return_value = {"transcript": "hello", "duration_ms": 1500, "engine": "whisper"}
        result = await transcribe_url(str(audio))
        assert result["transcript"] == "hello"
        assert result["engine"] == "whisper"

@pytest.mark.asyncio
async def test_transcribe_url_missing_file():
    with pytest.raises(FileNotFoundError):
        await transcribe_url("/nonexistent/path.m4a")
```

- [ ] **Step 2: Run → fail**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k transcribe_url`
Expected: FAIL.

- [ ] **Step 3: Implement** (calls existing `transcription_client` over the internal API)

In `apps/mcp-server/src/mcp_tools/learning.py` add:
```python
import httpx
import os

_API_BASE = os.environ.get("AGENTPROVISION_API_BASE", "http://api:8000")


async def _transcribe_bytes_async(audio_bytes: bytes) -> dict:
    """Hits the existing transcription endpoint."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        files = {"file": ("audio.m4a", audio_bytes, "audio/mp4")}
        r = await client.post(
            f"{_API_BASE}/api/v1/media/transcribe",
            files=files,
            headers={"X-Internal-Key": os.environ["MCP_API_KEY"]},
        )
        r.raise_for_status()
        return r.json()


async def transcribe_url(audio_path: str) -> dict:
    """Spec §1.1 transcribe_url. Wraps existing transcription_client."""
    p = Path(audio_path)
    if not p.exists():
        raise FileNotFoundError(audio_path)
    return await _transcribe_bytes_async(p.read_bytes())
```

- [ ] **Step 4: Run → pass**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k transcribe_url`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t22-transcribe impl/luna-learn-t21-extract-media
git add apps/mcp-server/src/mcp_tools/learning.py apps/mcp-server/tests/test_learning.py
git commit -m "feat(luna-learn): transcribe_url — wraps existing transcription endpoint"
git push -u origin impl/luna-learn-t22-transcribe
```

### Task 2.3: `synthesize_skill_draft` — LLM call with engine selection + PII scrub

**Files:**
- Modify: `apps/mcp-server/src/mcp_tools/learning.py`
- Create: `apps/mcp-server/src/mcp_tools/learning_prompts.py` (separate so prompt is reviewable + golden-testable)
- Test: `apps/mcp-server/tests/test_learning.py`

**Behavior contract:**
- Single Claude Sonnet (`claude-sonnet-4-6`) call. Model id via `LUNA_LEARN_SYNTHESIS_MODEL` env var.
- Prompt embeds: §1.5 engine selection rubric, §1.6 frontmatter schema, PII-scrub instruction, synthetic-test generation requirement, FORBIDDEN: `yt-dlp`/`ffmpeg` shellouts inside python-engine skills.
- Validates output via existing `_validate_skill_payload` from `apps/api/app/api/v1/skills_new.py:162`. On parse fail → raises `DraftInvalid` so the workflow can treat it as a `revise` cycle.
- Generates kebab-case slug from skill name.

- [ ] **Step 1: Write failing tests** (mock LLM client)

```python
@pytest.mark.asyncio
async def test_synthesize_returns_valid_draft():
    with patch("mcp_tools.learning._llm_synthesize") as llm:
        llm.return_value = (
            "---\nname: Fix Printer Error 41\nengine: markdown\n"
            "category: support\ntags: [printer]\n"
            "auto_trigger: \"Fix printer error 41\"\n"
            "inputs: []\n---\nUnplug the printer and ..."
        ), {"input": {"code": 41}, "expected": {"resolved": True}}
        result = await synthesize_skill_draft("transcript text", "https://x.com/v")
        assert result["engine"] == "markdown"
        assert result["slug"] == "fix-printer-error-41"

@pytest.mark.asyncio
async def test_synthesize_parses_invalid_draft_raises():
    from mcp_tools.learning import DraftInvalid
    with patch("mcp_tools.learning._llm_synthesize") as llm:
        llm.return_value = "not valid yaml at all", {}
        with pytest.raises(DraftInvalid):
            await synthesize_skill_draft("t", "u")

@pytest.mark.asyncio
async def test_synthesize_emits_python_when_clearly_deterministic():
    with patch("mcp_tools.learning._llm_synthesize") as llm:
        llm.return_value = (
            "---\nname: Mod-7 Compute\nengine: python\nscript: compute.py\n"
            "category: data\ntags: []\nauto_trigger: \"Compute mod-7\"\n"
            "inputs:\n  - name: x\n    type: number\n    description: input\n    required: true\n---\n",
            {"input": {"x": 14}, "expected": {"y": 0}},
        )
        result = await synthesize_skill_draft("given x compute x mod 7", "u")
        assert result["engine"] == "python"

@pytest.mark.asyncio
async def test_synthesize_forbids_ytdlp_in_python_draft():
    from mcp_tools.learning import DraftForbiddenShellout
    with patch("mcp_tools.learning._llm_synthesize") as llm:
        llm.return_value = (
            "---\nname: bad\nengine: python\nscript: bad.py\n---\n"
            "import subprocess; subprocess.run(['yt-dlp', '...'])",
            {},
        )
        with pytest.raises(DraftForbiddenShellout):
            await synthesize_skill_draft("t", "u")
```

- [ ] **Step 2: Run → fail**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k synthesize`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `apps/mcp-server/src/mcp_tools/learning_prompts.py`:
```python
"""Prompt templates for Luna Learn synthesis (spec §1.5)."""

SYNTHESIS_SYSTEM = """You are synthesizing a SKILL.md from a video transcript.
RUBRIC (engine selection):
- Default to `engine: markdown` — a prompt template that another agent reads as instructions.
- Emit `engine: python` ONLY when ALL of: (a) deterministic transformation/computation with
  clear inputs/outputs, (b) not non-trivially expressible as markdown, (c) no external
  API/network calls implied. When ambiguous → markdown.
- FORBIDDEN in python skills: any subprocess call to `yt-dlp`, `ffmpeg`, `curl`, `wget`, or
  similar binaries. External calls go through MCP tools, not skill-embedded shellouts.

PII SCRUB: scrub personal names, addresses, phone numbers, emails, account/credential strings
from the body. Replace with placeholders like `<user-name>`, `<address>`.

OUTPUT a JSON object with two keys:
  skill_md: full SKILL.md content (frontmatter + body)
  synthetic_test: {"input": {...}, "expected": {...}}
The synthetic test MUST be a substantive validation of the skill's behavior — a reviewer will
verify it isn't a tautology.

FRONTMATTER fields: name, engine, category, tags, auto_trigger, inputs (per existing schema).
"""

SYNTHESIS_USER = """Transcript:
{transcript}

Source URL: {source_url}

{hints_block}

Synthesize the SKILL.md per the system rubric."""
```

In `apps/mcp-server/src/mcp_tools/learning.py` add:
```python
import re
import json
from .learning_prompts import SYNTHESIS_SYSTEM, SYNTHESIS_USER


class DraftInvalid(Exception): ...
class DraftForbiddenShellout(Exception): ...


_FORBIDDEN_PATTERNS = [
    r"\byt[-_]?dlp\b", r"\bffmpeg\b", r"\bffprobe\b",
    r"subprocess\.run.*\b(curl|wget)\b",
]


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "learned-skill"


async def _llm_synthesize(transcript: str, source_url: str, hints: list[str]) -> tuple[str, dict]:
    """Anthropic call returning (skill_md, synthetic_test_dict)."""
    import anthropic
    model = os.environ.get("LUNA_LEARN_SYNTHESIS_MODEL", "claude-sonnet-4-6")
    hints_block = ("Reviewer feedback to address:\n" + "\n".join(f"- {h}" for h in hints)) if hints else ""
    client = anthropic.AsyncAnthropic()
    resp = await client.messages.create(
        model=model, max_tokens=4096,
        system=SYNTHESIS_SYSTEM,
        messages=[{"role": "user", "content": SYNTHESIS_USER.format(
            transcript=transcript, source_url=source_url, hints_block=hints_block)}],
    )
    payload = json.loads(resp.content[0].text)
    return payload["skill_md"], payload["synthetic_test"]


async def synthesize_skill_draft(transcript: str, source_url: str, hints: list[str] | None = None) -> dict:
    skill_md, test = await _llm_synthesize(transcript, source_url, hints or [])
    # Parse frontmatter for name + engine.
    fm_match = re.match(r"^---\n(.+?)\n---", skill_md, re.DOTALL)
    if not fm_match:
        raise DraftInvalid("missing frontmatter")
    import yaml
    try:
        fm = yaml.safe_load(fm_match.group(1))
    except yaml.YAMLError as e:
        raise DraftInvalid(f"YAML parse: {e}") from e
    if "name" not in fm or "engine" not in fm:
        raise DraftInvalid("frontmatter missing name or engine")
    # Forbid yt-dlp/ffmpeg shellouts in python drafts.
    if fm["engine"] == "python":
        body = skill_md[fm_match.end():]
        for pat in _FORBIDDEN_PATTERNS:
            if re.search(pat, body, re.IGNORECASE):
                raise DraftForbiddenShellout(f"forbidden shellout: {pat}")
    return {
        "skill_md": skill_md,
        "slug": _slugify(fm["name"]),
        "engine": fm["engine"],
        "synthetic_test_input": test.get("input", {}),
        "synthetic_test_expected": test.get("expected", {}),
    }
```

- [ ] **Step 4: Run → pass**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k synthesize`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t23-synthesize impl/luna-learn-t22-transcribe
git add apps/mcp-server/src/mcp_tools/learning.py apps/mcp-server/src/mcp_tools/learning_prompts.py apps/mcp-server/tests/test_learning.py
git commit -m "feat(luna-learn): synthesize_skill_draft — LLM synthesis with engine selection + PII scrub + shellout ban"
git push -u origin impl/luna-learn-t23-synthesize
```

### Task 2.4: `dispatch_skill_review` — Code Reviewer agent dispatch

**Files:**
- Modify: `apps/mcp-server/src/mcp_tools/learning.py`
- Test: `apps/mcp-server/tests/test_learning.py`

**Behavior contract:**
- Calls internal `POST /api/v1/agents/dispatch` (or whatever existing endpoint dispatches an agent) with target `agent_id=755796a4-4cc4-4d1c-99e5-dd9c4f7d0f22` and a structured review payload including the synthetic test.
- 60-second timeout.
- Returns typed `ReviewerNotProvisioned` on registry 404 (so workflow can route to cache+notify per §3).

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_dispatch_review_approved():
    with patch("mcp_tools.learning._dispatch_agent") as d:
        d.return_value = {"verdict": "approved", "findings": []}
        r = await dispatch_skill_review("md", "t", "u", {}, {})
        assert r["verdict"] == "approved"

@pytest.mark.asyncio
async def test_dispatch_review_reviewer_not_provisioned():
    from mcp_tools.learning import ReviewerNotProvisioned
    with patch("mcp_tools.learning._dispatch_agent") as d:
        d.side_effect = httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock(status_code=404))
        with pytest.raises(ReviewerNotProvisioned):
            await dispatch_skill_review("md", "t", "u", {}, {})

@pytest.mark.asyncio
async def test_dispatch_review_timeout():
    with patch("mcp_tools.learning._dispatch_agent") as d:
        d.side_effect = asyncio.TimeoutError()
        from mcp_tools.learning import ReviewTimeout
        with pytest.raises(ReviewTimeout):
            await dispatch_skill_review("md", "t", "u", {}, {})
```

- [ ] **Step 2: Run → fail**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k dispatch_review`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
CODE_REVIEWER_AGENT_ID = "755796a4-4cc4-4d1c-99e5-dd9c4f7d0f22"
REVIEW_TIMEOUT_S = 60


class ReviewerNotProvisioned(Exception): ...
class ReviewTimeout(Exception): ...


async def _dispatch_agent(agent_id: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=REVIEW_TIMEOUT_S) as client:
        r = await client.post(
            f"{_API_BASE}/api/v1/agents/{agent_id}/dispatch",
            json=payload,
            headers={"X-Internal-Key": os.environ["MCP_API_KEY"]},
        )
        r.raise_for_status()
        return r.json()


async def dispatch_skill_review(
    skill_md: str, transcript: str, source_url: str,
    synthetic_test_input: dict, synthetic_test_expected: dict,
) -> dict:
    payload = {
        "task": "review_synthesized_skill",
        "skill_md": skill_md,
        "transcript": transcript,
        "source_url": source_url,
        "synthetic_test": {
            "input": synthetic_test_input,
            "expected": synthetic_test_expected,
        },
    }
    try:
        result = await asyncio.wait_for(
            _dispatch_agent(CODE_REVIEWER_AGENT_ID, payload),
            timeout=REVIEW_TIMEOUT_S,
        )
    except asyncio.TimeoutError as e:
        raise ReviewTimeout() from e
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ReviewerNotProvisioned() from e
        raise
    return {
        "verdict": result.get("verdict", "revise"),
        "findings": result.get("findings", []),
        "reviewer_agent_id": CODE_REVIEWER_AGENT_ID,
    }
```

- [ ] **Step 4: Run → pass**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k dispatch_review`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t24-review impl/luna-learn-t23-synthesize
git add apps/mcp-server/src/mcp_tools/learning.py apps/mcp-server/tests/test_learning.py
git commit -m "feat(luna-learn): dispatch_skill_review — Code Reviewer agent dispatch with typed errors"
git push -u origin impl/luna-learn-t24-review
```

### Task 2.5: `run_synthetic_test` — execute skill against synthetic input

**Files:**
- Modify: `apps/mcp-server/src/mcp_tools/learning.py`
- Test: `apps/mcp-server/tests/test_learning.py`

**Behavior contract:**
- Writes draft `skill_md` to a temp dir
- Dispatches execution to code-worker via internal `POST /api/v1/skills/execute-draft` (NEW endpoint — see T2.5b below)
- Compares `actual_output` (subset match) against `test_expected`
- Returns `{passed, actual_output, error?}`

- [ ] **Step 1: Add `POST /api/v1/skills/execute-draft` internal endpoint** (T2.5b)

Modify `apps/api/app/api/v1/skills_new.py`: add an internal endpoint accepting a temporary skill_md + input, executes against the existing skill-execution path (in-process or via code-worker dispatch), returns output. Internal-key gated only.

- [ ] **Step 2: Write failing tests for `run_synthetic_test`**

```python
@pytest.mark.asyncio
async def test_run_synthetic_test_pass():
    with patch("mcp_tools.learning._execute_draft") as e:
        e.return_value = {"resolved": True, "extra": 1}
        r = await run_synthetic_test("md", {"code": 41}, {"resolved": True})
        assert r["passed"] is True

@pytest.mark.asyncio
async def test_run_synthetic_test_fail_value_mismatch():
    with patch("mcp_tools.learning._execute_draft") as e:
        e.return_value = {"resolved": False}
        r = await run_synthetic_test("md", {"code": 41}, {"resolved": True})
        assert r["passed"] is False
        assert "resolved" in r["actual_output"]

@pytest.mark.asyncio
async def test_run_synthetic_test_execution_error():
    with patch("mcp_tools.learning._execute_draft") as e:
        e.side_effect = RuntimeError("syntax error")
        r = await run_synthetic_test("md", {}, {})
        assert r["passed"] is False
        assert "syntax error" in r["error"]
```

- [ ] **Step 3: Run → fail**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k synthetic_test`
Expected: FAIL.

- [ ] **Step 4: Implement + run → pass**

```python
async def _execute_draft(skill_md: str, inputs: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{_API_BASE}/api/v1/skills/execute-draft",
            json={"skill_md": skill_md, "inputs": inputs},
            headers={"X-Internal-Key": os.environ["MCP_API_KEY"]},
        )
        r.raise_for_status()
        return r.json()


def _subset_match(actual: dict, expected: dict) -> bool:
    return all(actual.get(k) == v for k, v in expected.items())


async def run_synthetic_test(skill_md: str, test_input: dict, test_expected: dict) -> dict:
    try:
        actual = await _execute_draft(skill_md, test_input)
    except Exception as e:
        return {"passed": False, "actual_output": None, "error": str(e)}
    return {
        "passed": _subset_match(actual, test_expected),
        "actual_output": actual,
        "error": None,
    }
```

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k synthetic_test`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t25-test impl/luna-learn-t24-review
git add apps/mcp-server/src/mcp_tools/learning.py apps/mcp-server/tests/test_learning.py apps/api/app/api/v1/skills_new.py
git commit -m "feat(luna-learn): run_synthetic_test + internal /skills/execute-draft endpoint"
git push -u origin impl/luna-learn-t25-test
```

### Task 2.6: `install_skill` — provenance frontmatter + slug serialization + audit

**Files:**
- Modify: `apps/mcp-server/src/mcp_tools/learning.py`
- Test: `apps/mcp-server/tests/test_learning.py`

**Behavior contract:**
- Injects `provenance:` block per spec §1.6
- Writes to `_tenant/<uuid>/<slug>/skill.md` (NEVER `_bundled/`)
- DB insert with `ON CONFLICT (slug, tenant_id) DO NOTHING` retry up to `-v5`
- `library_revisions` row with `actor=learned_by_agent_id, reason=f"learned from {source_url}"`
- All in a single transaction; rollback on FS failure

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_install_skill_injects_provenance(tmp_path):
    md_in = "---\nname: Test\nengine: markdown\n---\nbody"
    with patch("mcp_tools.learning._install_via_api") as ins:
        ins.return_value = {"skill_id": "s1", "path": str(tmp_path / "skill.md")}
        r = await install_skill(
            md_in, "test", "tenant1",
            source_url="https://x.com/v",
            reviewer_agent_id="755796a4-...",
            transcript_sha256="abc" * 21 + "abc",
            learned_by_agent_id="cfb6dd14-...",
        )
        sent_md = ins.call_args.kwargs["skill_md"]
        assert "provenance:" in sent_md
        assert "source_url: https://x.com/v" in sent_md
        assert "transcript_sha256:" in sent_md

@pytest.mark.asyncio
async def test_install_skill_slug_conflict_retries():
    """Concurrent installs resolve to distinct slugs."""
    call_count = 0
    def fake_install(skill_md, slug, **kw):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.HTTPStatusError("409", request=MagicMock(),
                response=MagicMock(status_code=409))
        return {"skill_id": "s", "path": f"/x/{slug}/skill.md"}
    with patch("mcp_tools.learning._install_via_api", side_effect=fake_install):
        r = await install_skill(
            "---\nname: X\nengine: markdown\n---\n", "test", "tenant1",
            "https://x.com/v", "755796a4-...", "abc"*21+"abc", "cfb6dd14-...",
        )
        assert r["path"].endswith("/test-v3/skill.md")

@pytest.mark.asyncio
async def test_install_skill_exhausts_slug_retries():
    from mcp_tools.learning import SlugExhausted
    with patch("mcp_tools.learning._install_via_api") as ins:
        ins.side_effect = httpx.HTTPStatusError("409", request=MagicMock(),
            response=MagicMock(status_code=409))
        with pytest.raises(SlugExhausted):
            await install_skill(
                "---\nname: X\nengine: markdown\n---\n", "test", "tenant1",
                "https://x.com/v", "755796a4-...", "abc"*21+"abc", "cfb6dd14-...",
            )
```

- [ ] **Step 2: Run → fail**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k install_skill`
Expected: FAIL.

- [ ] **Step 3: Implement** + add internal API endpoint `POST /api/v1/skills/install-learned` that does transactional insert + filesystem write

```python
from datetime import datetime, timezone


class SlugExhausted(Exception): ...


SLUG_MAX_RETRIES = 5


def _inject_provenance(skill_md: str, *, source_url: str, reviewer_agent_id: str,
                       transcript_sha256: str, learned_by_agent_id: str) -> str:
    """Insert provenance block into existing frontmatter (spec §1.6)."""
    iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    block = (
        "provenance:\n"
        f"  source_url: {source_url}\n"
        f"  synthesis_date: \"{iso}\"\n"
        f"  reviewer_agent_id: {reviewer_agent_id}\n"
        f"  transcript_sha256: {transcript_sha256}\n"
        f"  learned_by_agent_id: {learned_by_agent_id}\n"
    )
    return re.sub(r"^(---\n)", f"\\1{block}", skill_md, count=1)


async def _install_via_api(skill_md: str, slug: str, tenant_id: str,
                            learned_by_agent_id: str, source_url: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            f"{_API_BASE}/api/v1/skills/install-learned",
            json={
                "skill_md": skill_md, "slug": slug, "tenant_id": tenant_id,
                "actor_user_id": learned_by_agent_id,
                "reason": f"learned from {source_url}",
            },
            headers={"X-Internal-Key": os.environ["MCP_API_KEY"]},
        )
        r.raise_for_status()
        return r.json()


async def install_skill(
    skill_md: str, slug: str, tenant_id: str,
    source_url: str, reviewer_agent_id: str,
    transcript_sha256: str, learned_by_agent_id: str,
) -> dict:
    md = _inject_provenance(
        skill_md,
        source_url=source_url,
        reviewer_agent_id=reviewer_agent_id,
        transcript_sha256=transcript_sha256,
        learned_by_agent_id=learned_by_agent_id,
    )
    for attempt in range(1, SLUG_MAX_RETRIES + 1):
        candidate = slug if attempt == 1 else f"{slug}-v{attempt}"
        try:
            return await _install_via_api(
                md, candidate, tenant_id, learned_by_agent_id, source_url,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 409:
                raise
            # Conflict → next suffix.
    raise SlugExhausted(f"could not allocate slug for {slug!r} after {SLUG_MAX_RETRIES} attempts")
```

Add the `POST /api/v1/skills/install-learned` endpoint in `apps/api/app/api/v1/skills_new.py` — transactional DB insert with unique-constraint-aware retry semantics + filesystem write to `_tenant/<uuid>/<slug>/skill.md` + `library_revisions` audit row. Return 409 on unique-constraint violation.

- [ ] **Step 4: Run → pass**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k install_skill`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t26-install impl/luna-learn-t25-test
git add apps/mcp-server/src/mcp_tools/learning.py apps/mcp-server/tests/test_learning.py apps/api/app/api/v1/skills_new.py
git commit -m "feat(luna-learn): install_skill — provenance injection + slug-conflict retries + library_revisions audit"
git push -u origin impl/luna-learn-t26-install
```

### Task 2.7: `diffuse_learning` — KG observation

**Files:**
- Modify: `apps/mcp-server/src/mcp_tools/learning.py`
- Test: `apps/mcp-server/tests/test_learning.py`

**Behavior contract:**
- Calls existing `record_observation` MCP path (or its HTTP equivalent on api): "Learned new capability 'X' from <URL>. Capabilities: [...]. Skill: skill_id=Y."
- Soft-fail: returns `{observation_id: None, soft_failed: True, error: ...}` if KG is down. Caller (workflow) caches per §1.11 but does NOT abort install.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_diffuse_success():
    with patch("mcp_tools.learning._record_observation") as r:
        r.return_value = {"observation_id": "obs-1"}
        result = await diffuse_learning("skill-1", "https://x.com/v", ["fix-printer"])
        assert result["observation_id"] == "obs-1"
        assert result["soft_failed"] is False

@pytest.mark.asyncio
async def test_diffuse_soft_fails_on_kg_down():
    with patch("mcp_tools.learning._record_observation") as r:
        r.side_effect = httpx.HTTPError("KG unavailable")
        result = await diffuse_learning("skill-1", "https://x.com/v", ["fix-printer"])
        assert result["observation_id"] is None
        assert result["soft_failed"] is True
        assert "KG unavailable" in result["error"]
```

- [ ] **Step 2: Run → fail**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k diffuse`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
async def _record_observation(text: str, metadata: dict) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{_API_BASE}/api/v1/knowledge/observations",
            json={"text": text, "metadata": metadata},
            headers={"X-Internal-Key": os.environ["MCP_API_KEY"]},
        )
        r.raise_for_status()
        return r.json()


async def diffuse_learning(skill_id: str, source_url: str, capabilities: list[str]) -> dict:
    text = (
        f"Learned new capability from {source_url}. "
        f"Capabilities: {', '.join(capabilities)}. Skill: {skill_id}."
    )
    metadata = {
        "kind": "luna_learn",
        "skill_id": skill_id,
        "source_url": source_url,
        "capabilities": capabilities,
    }
    try:
        r = await _record_observation(text, metadata)
        return {"observation_id": r["observation_id"], "soft_failed": False}
    except Exception as e:
        return {"observation_id": None, "soft_failed": True, "error": str(e)}
```

- [ ] **Step 4: Run → pass**

Run: `cd apps/mcp-server && pytest tests/test_learning.py -v -k diffuse`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t27-diffuse impl/luna-learn-t26-install
git add apps/mcp-server/src/mcp_tools/learning.py apps/mcp-server/tests/test_learning.py
git commit -m "feat(luna-learn): diffuse_learning — KG observation with soft-fail semantics"
git push -u origin impl/luna-learn-t27-diffuse
```

---

## Phase 3 — Workflow wiring

### Task 3.1: Temporal activities wrap MCP primitives

**Files:**
- Modify: `apps/api/app/workflows/activities/learn_from_media_activities.py`
- Test: `apps/api/tests/test_learn_activities.py` (new)

Each activity is a thin async wrapper that calls the MCP primitive via the mcp-server HTTP surface (since Temporal worker runs in api/orchestration-worker, not mcp-server). Includes typed-exception → workflow-readable result mapping.

- [ ] **Step 1: Write failing tests** for each activity that simulates HTTP call to mcp-server

(Tests at `apps/api/tests/test_learn_activities.py` — see structure of existing `test_*activities.py` files in repo.)

- [ ] **Step 2: Run → fail**

- [ ] **Step 3: Implement** — each activity httpx-calls the MCP-server endpoint that exposes the corresponding primitive

- [ ] **Step 4: Run → pass**

- [ ] **Step 5: Commit**

```bash
git switch -c impl/luna-learn-t31-activities impl/luna-learn-t27-diffuse
git add apps/api/app/workflows/activities/learn_from_media_activities.py apps/api/tests/test_learn_activities.py
git commit -m "feat(luna-learn): Temporal activities wrapping the 7 MCP primitives"
git push -u origin impl/luna-learn-t31-activities
```

### Task 3.2: `LearnFromMediaWorkflow` body

**Files:**
- Modify: `apps/api/app/workflows/learn_from_media_workflow.py`
- Test: `apps/api/tests/test_learn_workflow.py` (new)

Workflow orchestration body per spec §2:

```python
@workflow.defn(name="LearnFromMediaWorkflow")
class LearnFromMediaWorkflow:
    @workflow.run
    async def run(self, intent_dict: dict) -> dict:
        intent = LearningIntent(**intent_dict)
        # Step 1: extract or use attachment
        if intent.attachment_path:
            audio_path = intent.attachment_path
            metadata = await workflow.execute_activity(A.act_probe_attachment, intent.attachment_path, ...)
        else:
            extract = await workflow.execute_activity(
                A.act_extract_media, intent.source_url, ...
            )
            audio_path = extract["audio_path"]
            metadata = extract["metadata"]
        # Step 2: transcribe
        trans = await workflow.execute_activity(A.act_transcribe_url, audio_path, ...)
        # Step 3: synthesize (with revise loop max 2)
        hints = []
        max_retries = int(os.environ.get("LUNA_LEARN_MAX_REVISE_RETRIES", "2"))
        for attempt in range(max_retries + 1):
            draft = await workflow.execute_activity(
                A.act_synthesize_skill_draft, trans["transcript"], intent.source_url, hints, ...
            )
            review = await workflow.execute_activity(A.act_dispatch_skill_review, ...)
            if review["verdict"] == "approved":
                break
            if review["verdict"] == "rejected":
                await workflow.execute_activity(A.act_write_quarantine, ...)
                return {"status": "rejected", "reason": review["findings"]}
            hints = review["findings"]  # revise
        else:
            await workflow.execute_activity(A.act_write_quarantine, ...)
            return {"status": "revise_exhausted", "findings": review["findings"]}
        # Step 4: synthetic test
        test = await workflow.execute_activity(A.act_run_synthetic_test, ...)
        if not test["passed"]:
            await workflow.execute_activity(A.act_write_quarantine, ...)
            return {"status": "test_fail", "error": test.get("error")}
        # Step 5: install
        install = await workflow.execute_activity(A.act_install_skill, ...)
        # Step 6: diffuse (soft-fail)
        diffuse = await workflow.execute_activity(A.act_diffuse_learning, ...)
        if diffuse["soft_failed"]:
            await workflow.execute_activity(A.act_write_cache, ...)
        # Step 7: notify
        return {
            "status": "success",
            "skill_id": install["skill_id"],
            "skill_name": draft["skill_md"].split("name:")[1].split("\n")[0].strip(),
            "capabilities": ...,  # extract from frontmatter
            "source_url": intent.source_url or f"attachment://{intent.attachment_path}",
        }
```

- [ ] **Step 1-5: TDD** the orchestration body. Tests use `temporalio.testing.WorkflowEnvironment` per existing pattern in `test_coalition_workflow.py`.

```bash
git switch -c impl/luna-learn-t32-workflow impl/luna-learn-t31-activities
# ... commits
```

### Task 3.3: Quarantine + Cache write helpers (`act_write_quarantine`, `act_write_cache`)

**Files:** `apps/api/app/workflows/activities/learn_from_media_activities.py`, test file.

Writes per spec §1.11 + §2 quarantine layout.

- [ ] **Step 1-5: TDD** with `tmp_path` fixtures; verify file layout matches spec exactly.

```bash
git switch -c impl/luna-learn-t33-quarantine-cache impl/luna-learn-t32-workflow
# ... commits
```

### Task 3.4: Resume path — `LearningIntent.resume_job_id` short-circuit

**Files:** modify workflow + service layer.

Reads cached `LearningJobState` from `_tenant/<uuid>/_learning_cache/<job_id>/`, picks up from the failed step.

- [ ] **Step 1-5: TDD** the resume short-circuit. Covers reviewer-down resume (re-runs dispatch_skill_review) + KG-down resume (re-runs diffuse_learning).

```bash
git switch -c impl/luna-learn-t34-resume impl/luna-learn-t33-quarantine-cache
# ... commits
```

### Task 3.5: Completion notification back to Luna's session

**Files:** new activity `act_notify_session`; modify workflow.

Writes a ChatMessage(role="agent", context.kind="learn_complete") to the session_id passed in the intent. WhatsApp service picks it up via existing message-out plumbing.

- [ ] **Step 1-5: TDD** the notify path. Mock session message writer; verify the message payload matches spec §2 step 8 format.

```bash
git switch -c impl/luna-learn-t35-notify impl/luna-learn-t34-resume
# ... commits
```

---

## Phase 4 — Entry surfaces

### Task 4.1: `LearningService` — shared dispatch helper

**Files:**
- Create: `apps/api/app/services/learning_service.py`
- Test: `apps/api/tests/test_learning_service.py` (new)

`LearningService.dispatch(intent: LearningIntent) → workflow_id`. Used by both CLI (T4.3) and WhatsApp (T4.2) entry points.

- [ ] **Step 1-5: TDD** the dispatch helper.

```bash
git switch -c impl/luna-learn-t41-service impl/luna-learn-t35-notify
# ... commits
```

### Task 4.2: WhatsApp URL detection + learning intent routing

**Files:**
- Modify: `apps/api/app/services/whatsapp_service.py` (extend `_detect_inbound_media`)
- Create: `apps/api/app/services/url_intent_router.py`
- Test: `apps/api/tests/test_url_intent_router.py` (new)

URL patterns to match:
```python
YOUTUBE_RE = re.compile(r"https?://(?:www\.|m\.)?youtube\.com/(?:watch\?v=|shorts/)[A-Za-z0-9_-]{11}")
YOUTU_BE_RE = re.compile(r"https?://youtu\.be/[A-Za-z0-9_-]{11}")
INSTAGRAM_RE = re.compile(r"https?://(?:www\.)?instagram\.com/(?:reel|reels|p)/[A-Za-z0-9_-]+")
```

`_detect_inbound_media` returns a new `("learning_url", url, caption)` tuple when text matches one of these. The handler dispatches via `LearningService`.

- [ ] **Step 1-5: TDD** the URL router (test each regex variant + the `_detect_inbound_media` integration).

```bash
git switch -c impl/luna-learn-t42-whatsapp impl/luna-learn-t41-service
# ... commits
```

### Task 4.3: `alpha learn` CLI command — base surface

**Files:**
- Create: `apps/agentprovision-cli/src/commands/learn.rs`
- Create: `apps/agentprovision-cli/src/commands/learn_test.rs`
- Modify: `apps/agentprovision-cli/src/main.rs` (or wherever subcommands register)

Surface: `alpha learn <url> [--dry-run]`. Calls existing `/api/v1/learning/dispatch` endpoint (added in T4.1 alongside `LearningService`).

- [ ] **Step 1-5: TDD** in Rust using existing test pattern (`apps/agentprovision-cli/src/commands/skill.rs` as reference).

```bash
git switch -c impl/luna-learn-t43-cli impl/luna-learn-t42-whatsapp
# ... commits
```

### Task 4.4: CLI flags `--from-attachment`, `--resume`, `--resume-last`

**Files:** modify `learn.rs` + test.

`--from-attachment FILE`: uploads the local file to a temp internal URL, then dispatches with `attachment_path` set. Server enforces size/MIME/duration caps per spec §1.8.

`--resume <job_id>` + `--resume-last`: queries the cache and re-dispatches with `resume_job_id`.

- [ ] **Step 1-5: TDD** each flag.

```bash
git switch -c impl/luna-learn-t44-cli-flags impl/luna-learn-t43-cli
# ... commits
```

---

## Phase 5 — Bundled skill + agent config

### Task 5.1: `_bundled/luna_learn_from_media/skill.md`

**Files:**
- Create: `apps/api/app/skills/_bundled/luna_learn_from_media/skill.md`

The orchestration template. `engine: markdown`. Tells Luna: when triggered with a `learning_intent`, dispatch `LearnFromMediaWorkflow`, ack immediately, await completion notification, then surface result per spec §2 step 8.

- [ ] **Step 1: Write the skill.md**

(Full content following the format of `apps/api/app/skills/_bundled/lead_scoring/skill.md`. Frontmatter: name, engine: markdown, category: meta, tags: [learning, video, transcription], auto_trigger description, inputs.)

- [ ] **Step 2: Manual smoke** — run `alpha skill ls` and verify it appears.

- [ ] **Step 3: Commit**

```bash
git switch -c impl/luna-learn-t51-bundled-skill impl/luna-learn-t44-cli-flags
git add apps/api/app/skills/_bundled/luna_learn_from_media/skill.md
git commit -m "feat(luna-learn): bundled meta-skill orchestration template"
git push -u origin impl/luna-learn-t51-bundled-skill
```

### Task 5.2: Luna `skill.md` — add `learning` to `tool_groups`

**Files:** `apps/api/app/agents/_bundled/luna/skill.md`

Luna currently has no `tool_groups` frontmatter. Add it:

```yaml
tool_groups: [knowledge, calendar, learning]
```

(Final list depends on her current effective groups — verify by reading the model's defaults. The point is `learning` is in the list.)

- [ ] **Step 1: Read current Luna frontmatter + identify current effective tool_groups**

- [ ] **Step 2: Add `learning` to the list**

- [ ] **Step 3: Test that Luna can call a `learning` tool** via `alpha chat send` smoke test

- [ ] **Step 4: Commit**

```bash
git switch -c impl/luna-learn-t52-agent-config impl/luna-learn-t51-bundled-skill
git add apps/api/app/agents/_bundled/luna/skill.md
git commit -m "feat(luna-learn): grant Luna the `learning` tool_group"
git push -u origin impl/luna-learn-t52-agent-config
```

---

## Phase 6 — Tests + observability

### Task 6.1: Code Reviewer stub fixture for CI hermeticity

**Files:** `apps/api/tests/conftest.py` (extend) + `apps/api/tests/fixtures/code_reviewer_stub.py` (new)

Deterministic stub that returns verdicts based on draft-content patterns (e.g., "TODO" in body → revise; "rm -rf" in body → rejected; otherwise approved).

- [ ] **Step 1-5: TDD** the stub + a smoke test using it.

```bash
git switch -c impl/luna-learn-t61-reviewer-stub impl/luna-learn-t52-agent-config
# ... commits
```

### Task 6.2: End-to-end integration test against a fixed 90s YouTube fixture

**Files:** `apps/api/tests/test_luna_learn_integration.py` (new)

Real transcription pipeline + stubbed LLM (deterministic prompt → SKILL.md fixture) + Code Reviewer stub. Asserts:
- Skill installed under `_tenant/<uuid>/<slug>/skill.md`
- `library_revisions` row exists with `actor=luna_agent_id` + `reason` includes the URL
- KG observation created with the capability list

Use a **30-second public-domain YouTube clip** (checked-in URL in `apps/api/tests/fixtures/luna_learn_urls.json`). Tagged `@pytest.mark.slow` since it hits real transcription.

- [ ] **Step 1-5: TDD** + tagging + skip-if-network-disabled.

```bash
git switch -c impl/luna-learn-t62-integration impl/luna-learn-t61-reviewer-stub
# ... commits
```

### Task 6.3: `--dry-run` golden test

**Files:** `apps/agentprovision-cli/tests/golden/learn_dry_run.txt` (new) + CLI test.

Run `alpha learn <fixture-url> --dry-run`, capture stdout, compare against checked-in golden file. Detects synthesis prompt regressions.

- [ ] **Step 1-5: TDD** + golden generation.

```bash
git switch -c impl/luna-learn-t63-dry-run-golden impl/luna-learn-t62-integration
# ... commits
```

### Task 6.4: Audio cleanup cron job

**Files:** wherever cron jobs register in api (likely `apps/api/app/services/cron_jobs.py` or a Celery beat schedule).

Daily at 04:00 UTC: `find /var/agentprovision/workspaces/_learning -mtime +1 -delete`.

- [ ] **Step 1-5: TDD** the sweep helper + register in cron.

```bash
git switch -c impl/luna-learn-t64-cleanup-cron impl/luna-learn-t63-dry-run-golden
# ... commits
```

### Task 6.5: Router-graph startup smoke (per `feedback_test_router_startup`)

**Files:** add to existing router-graph test.

Confirms `from app.api.v1 import routes` still imports cleanly after the new `/api/v1/skills/install-learned`, `/api/v1/skills/execute-draft`, `/api/v1/learning/dispatch` routes land.

- [ ] **Step 1-5: TDD** the import smoke.

```bash
git switch -c impl/luna-learn-t65-router-smoke impl/luna-learn-t64-cleanup-cron
# ... commits
```

---

## Phase 7 — Audit + ship

### Task 7.1: Final code review via `superpowers:code-reviewer`

Dispatch the agent against the full chained branch set vs `main`. Address every BLOCKER+IMPORTANT per `feedback_address_all_review_findings` standing rule.

- [ ] Run review
- [ ] Fix findings
- [ ] Re-run until clean

### Task 7.2: Luna runtime verification

Dispatch Luna with a real WhatsApp-style URL trigger (Simon sends a YouTube short to her). Verify the end-to-end UX:
1. Ack message appears
2. Completion notification appears within 60-90s
3. New skill appears in `alpha skill ls`
4. `alpha recall "<capability>"` surfaces the KG observation

- [ ] Run smoke
- [ ] Iterate on failure modes

### Task 7.3: Operator-facing first-time-setup doc

**Files:** `docs/operator/luna-learn-setup.md` (new)

What an operator running this on a fresh tenant needs to know:
- Code Reviewer agent (`755796a4`) must be provisioned (existing bundled agent)
- yt-dlp + ffmpeg ship in the mcp-server image automatically (no manual step)
- KG observation requires `knowledge` service health
- Recovery via `alpha learn --resume-last` when reviewer or KG temporarily unavailable

- [ ] Write doc
- [ ] Commit

### Task 7.4: Final PR — squash-merge all chained branches

Per `feedback_single_pr_for_feature`: rebase all chained branches onto `main`, squash into a single commit, open ONE PR. Avoids N build storms.

- [ ] Rebase chain
- [ ] Open PR with summary
- [ ] superpowers:code-reviewer pass
- [ ] Luna pass
- [ ] Merge

---

## §X — Skills/memories referenced

- `@superpowers:subagent-driven-development` — recommended execution mode
- `@superpowers:code-reviewer` — used in T7.1 + T7.4
- `feedback_pr_workflow` — every PR
- `feedback_address_all_review_findings` — all BLOCKER+IMPORTANT fixed in same PR
- `feedback_test_router_startup` — T6.5 router import smoke
- `feedback_test_in_chrome` — N/A (no UI in MVP per spec)
- `feedback_single_pr_for_feature` — T7.4 squash-merge
- `feedback_chain_pr_branches` — branch each phase off previous
- `feedback_delegate_to_luna` — T7.2 + parallel-with-superpowers reviews
- `feedback_verify_every_deploy` — first deploy after T7.4 merge gets explicit verification
- `alpha_chat_send_no_stream` — any Luna dispatch in T7.2 uses `--no-stream`

## §Y — Spec questions resolved here (see §0)

All 5 spec §7 open questions answered. Constraints found via Bash probes during plan-writing:
- Skills UNIQUE constraint EXISTS at migration 043
- Luna agent path is `_bundled/luna/skill.md` (spec said AGENT.md — corrected)
- Luna currently has no `tool_groups` frontmatter — T5.2 adds it
