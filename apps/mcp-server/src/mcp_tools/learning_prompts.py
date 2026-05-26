"""Prompt templates for Luna Learn synthesis (spec §1.5).

Kept in a dedicated module so the prompt — which IS the contract between
the workflow and the LLM — is reviewable as a stand-alone artifact and
can grow snapshot tests without dragging in the rest of ``learning.py``.

When you edit ``SYNTHESIS_SYSTEM``, treat it as you'd treat changing an
API schema: it ripples through every learned skill the system will ever
produce. Reviewer feedback (the ``hints`` parameter to
``synthesize_skill_draft``) flows in through ``SYNTHESIS_USER`` on revise
cycles so the LLM gets the prior reviewer's complaints verbatim.
"""

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
