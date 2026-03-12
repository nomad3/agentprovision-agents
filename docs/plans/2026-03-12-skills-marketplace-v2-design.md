# Skills Marketplace v2 — Design Document

**Date:** 2026-03-12
**Goal:** Build a full-featured skills marketplace with vector-powered auto-trigger, three-tier skill system, chaining, versioning, and semantic memory — modeled after Claude Code's superpowers plugin architecture.

**Architecture:** Unified file-on-disk + DB metadata system. pgvector on Cloud SQL with Gemini Embedding 2 powers semantic search across skills, knowledge, and memory. Luna gets automatic context assembly before every LLM call.

**Tech Stack:** PostgreSQL + pgvector, Gemini Embedding 2 (`gemini-embedding-2-preview`, 768 dims), google-genai Python SDK, React 18 frontend.

---

## 1. Database & Embedding Foundation

### pgvector Setup
- Enable `CREATE EXTENSION vector` on Cloud SQL (migration 050)
- Add `google-genai` Python dependency to API requirements

### New Table: `embeddings`
Polymorphic embedding store for all content types.

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid FK, nullable | NULL for global content (native skills) |
| content_type | varchar | 'skill', 'entity', 'memory_activity', 'chat_message', 'relation', 'agent_task' |
| content_id | varchar | FK to source record |
| embedding | vector(768) | 768-dim Gemini output |
| text_content | text | Original text that was embedded |
| task_type | varchar | Gemini task type used |
| model | varchar | 'gemini-embedding-2-preview' |
| created_at | timestamp | |
| updated_at | timestamp | |

Indexes: GIN on `(tenant_id, content_type)`, IVFFlat on `embedding`.

### New Table: `skill_registry`
DB metadata for file-based skills.

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid FK, nullable | NULL for native/community |
| slug | varchar unique | Directory name |
| name | varchar | |
| version | int | Default 1, auto-increment on update |
| tier | varchar | 'native', 'custom', 'community' |
| category | varchar | sales, marketing, data, coding, communication, automation, general |
| tags | jsonb | Freeform tags |
| auto_trigger_description | text | Semantic trigger for Luna |
| chain_to | jsonb | List of skill slugs |
| engine | varchar | python, shell, markdown |
| is_published | bool | For community sharing |
| source_repo | varchar, nullable | GitHub origin URL |
| created_at | timestamp | |
| updated_at | timestamp | |

### New Service: `embedding_service.py`
- `embed_text(text, task_type) -> List[float]` — calls Gemini API
- `embed_and_store(tenant_id, content_type, content_id, text, task_type)` — embed + persist
- `search_similar(tenant_id, content_types, query_text, limit) -> List[dict]` — cosine distance search
- `recall(tenant_id, query, limit=20)` — unified search across ALL content types
- `bulk_embed(items)` — batch embedding for backfill
- `delete_embedding(content_type, content_id)` — cascade cleanup
- Uses `GOOGLE_API_KEY` env var

---

## 2. Unified Skill System — Three Tiers

### Tier 1: Native Skills (bundled, read-only)
- Ship with container image in `apps/api/app/skills/`
- Seeded to persistent volume on first boot
- Cannot be edited or deleted by tenants
- `tier = 'native'`, `tenant_id = NULL`
- Default available to all new users

### Tier 2: My Skills (tenant-scoped, full CRUD)
- Created by tenant via UI or API
- Stored in `{DATA_STORAGE_PATH}/skills/tenant_{tenant_id}/`
- Full edit, version, delete
- `tier = 'custom'`, `tenant_id = <uuid>`
- Can be forked from Native or Community

### Tier 3: Community Skills (GitHub-imported, shared)
- Imported from GitHub repos
- Stored in `{DATA_STORAGE_PATH}/skills/community/`
- `tier = 'community'`, `tenant_id = NULL`, `source_repo` set
- Read-only until tenant forks → becomes My Skill copy
- Visible to all tenants

### Directory Structure
```
/app/storage/skills/
  native/
    lead_scorer/
    report_generator/
  tenant_{uuid}/
    my_custom_scraper/
  community/
    awesome_email_parser/
```

### Skill Directory Structure (v2)
```
skill_name/
  skill.md            # YAML frontmatter + description
  script.py           # Engine script (python/shell)
  prompts/            # Sub-prompts folder
    scoring_rubric.md
    output_format.md
  CHANGELOG.md        # Auto-generated version history
```

### skill.md v2 Frontmatter
```yaml
---
name: Lead Scorer
engine: python
script_path: script.py
version: 3
category: sales
tags: [leads, scoring, crm]
auto_trigger: "When the user asks to score, qualify, or rank a lead or prospect"
chain_to: [knowledge_search, report_generator]
inputs:
  - name: entity_id
    type: string
    description: "Knowledge entity UUID to score"
    required: true
prompts:
  - scoring_rubric.md
  - output_format.md
---

## Description
Scores leads using configurable rubrics against the knowledge graph.
```

### Skill Access Rules
- `list_skills(tenant_id)` returns: all native + tenant's custom + all community
- Native skills "just work" for all new users — no setup needed
- Advanced users create custom skills or import community skills

---

## 3. Auto-Trigger & Skill Chaining

### Auto-Trigger Flow
1. User sends message to Luna
2. `embedding_service.search_similar(tenant_id, 'skill', user_message, limit=3)`
3. If top result similarity > 0.75 → inject skill content into system prompt
4. Luna follows instructions (markdown) or calls `run_skill` tool (python/shell)

### Embedding per Skill
- `auto_trigger` + `description` concatenated → one embedding
- Store: task_type `RETRIEVAL_DOCUMENT`
- Search: task_type `RETRIEVAL_QUERY`

### Skill Chaining
- `chain_to: [skill_a, skill_b]` in frontmatter
- Python/shell: return value passed as input to next skill
- Markdown: next skill's prompts appended to LLM context
- Linear chain only — no branching
- Max chain depth: 3
- Tenant's skills can only chain to accessible skills

---

## 4. Versioning

- `version` field in frontmatter, auto-incremented on update
- `skill_manager.update_skill()` bumps version, appends diff summary to CHANGELOG.md
- `skill_manager.rollback_skill(slug, version)` restores from local git history
- Skills persistent volume initialized with `git init` for version tracking
- CHANGELOG.md auto-generated, human-readable

---

## 5. Vector-First Memory

### All Memory Reads Go Through pgvector

| Content | Embedded Text | When |
|---|---|---|
| Skills | auto_trigger + description | create/update |
| Knowledge entities | name + category + description + properties | create/update |
| Knowledge relations | from.name + type + to.name + description | create/update |
| Memory activities | event_type + description + metadata summary | on log |
| Chat messages | message text (user + Luna) | on send |
| Agent task results | task description + result summary | on completion |

### Semantic Context Assembly (every LLM call)
1. Embed user message with `RETRIEVAL_QUERY`
2. `recall(tenant_id, user_message, limit=20)` — searches all content types
3. Group results: skills, entities, memories, past conversations
4. Inject grouped context into system prompt
5. LLM call

### Deprecate ILIKE
- `knowledge.py` search → vector similarity
- `memory_activity.py` queries → vector similarity
- Chat history context → vector similarity (most relevant, not last N)
- Agent memory lookup → vector similarity

### Memory Activity Events (skills)
- `skill_created`, `skill_executed`, `skill_failed`
- `skill_triggered` — auto-trigger matched
- `skill_forked` — tenant forked a skill
- `skill_imported` — GitHub import

### Embedding Lifecycle
- Create: embed immediately after write
- Update: delete old, create new
- Delete: cascade delete embedding
- Backfill: migration embeds all existing entities, activities, recent chat

---

## 6. UI — Skills Marketplace

### Layout
```
┌─────────────────────────────────────────────────┐
│ Skills Marketplace                    [+ Create] │
│ [Search skills...________________] [Import GitHub]│
│                                                   │
│ [My Skills (3)] [Native (8)] [Community (2)]     │
│                                                   │
│ [sales] [marketing] [data] [coding] [all]        │
│                                                   │
│ ┌──────────────┐ ┌──────────────┐ ┌────────────┐│
│ │ Lead Scorer  │ │ Report Gen   │ │ Know Search││
│ │ sales · v3   │ │ data · v1    │ │ general·v2 ││
│ │ python       │ │ markdown     │ │ python     ││
│ │ [Run] [···]  │ │ [Run] [···]  │ │ [Run] [···]││
│ └──────────────┘ └──────────────┘ └────────────┘│
└─────────────────────────────────────────────────┘
```

### Categories (fixed set)
sales, marketing, data, coding, communication, automation, general

### Card Interactions
- Click → inline expand: description, inputs, sub-prompts, chain info, version
- [Run] → execute modal
- [...] menu varies by tier:
  - My Skills: Edit, Version History, Delete
  - Native: Fork to My Skills, View Source
  - Community: Fork to My Skills, View Source, View GitHub

### Create Modal (My Skills only)
Name, category dropdown, engine picker, auto-trigger description, script editor, add sub-prompts, chain-to multi-select.

### Search
Hybrid: vector similarity on embeddings + text fallback on name/tags. Category chips filter results.

---

## 7. API Changes Summary

### New Endpoints
- `GET /api/v1/memory/search?q=<text>&types=skill,entity,memory` — unified semantic search
- `GET /api/v1/skills/library/match?q=<text>` — skill auto-trigger match (for ADK)
- `PUT /api/v1/skills/library/{slug}` — update skill (My Skills)
- `POST /api/v1/skills/library/{slug}/fork` — fork to My Skills
- `GET /api/v1/skills/library/{slug}/versions` — version history
- `POST /api/v1/skills/library/{slug}/rollback` — rollback to version

### Modified Endpoints
- `GET /api/v1/skills/library` — add `tier`, `category`, `search` query params
- Knowledge search endpoints — switch from ILIKE to vector similarity

### New Secrets
- `GOOGLE_API_KEY` — for Gemini Embedding 2 API calls

### New Dependencies
- `google-genai` — Gemini Python SDK
- `pgvector` — SQLAlchemy pgvector extension

---

## 8. Infrastructure Changes

### Cloud SQL
- Enable pgvector extension
- Migration 050: `CREATE EXTENSION vector`, create `embeddings` table, create `skill_registry` table
- Migration 051: Add `embedding_id` to `knowledge_entities`, backfill embeddings

### Helm
- Add `GOOGLE_API_KEY` secret to API + ADK + worker values
- Skills persistent volume already exists at `/app/storage`

### ADK Server
- Update `skill_tools.py` to use new match endpoint for auto-trigger
- Update context assembly to include semantic memory recall
