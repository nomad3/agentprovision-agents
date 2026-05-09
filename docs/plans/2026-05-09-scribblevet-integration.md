# Plan — ScribbleVet Integration: Clinical Notes → Knowledge Graph

**Owner:** Integration adapter + research
**Tenant:** The Animal Doctor SOC (`7f632730-1a38-41f1-9f99-508d696dbcf1`); generalize to every VMG tenant
**Why:** Angelo already pays for ScribbleVet (DVM-facing AI scribe in the exam room). It produces structured visit notes — but those notes live in ScribbleVet's silo, never reach AgentProvision's memory. The Clinical Triage Agent and Pet Health Concierge can only reference prior visits when ScribbleVet output flows into the knowledge graph. Without this, "is Bella's joint pain the same one she came in for in March?" can't be answered without a manual Pulse lookup.

## Goal

Read ScribbleVet exam-scribe output (per-visit) and ingest it as `clinical_note` observations on the patient entity. Trigger downstream effects: Clinical Triage references prior notes when drafting intake summaries; Pet Health Concierge surfaces prior conditions when the client asks record-aware questions; the Bookkeeper notices the visit billed for procedure-code-class from the SOAP.

## Deliverables

1. **Research artifact** — `docs/research/2026-05-09-scribblevet-api-research.md` covering: ScribbleVet's public API, webhook surface, export formats, OAuth/key auth, rate limits, retention. (Block: no public docs surveyed yet — this plan starts with research.)
2. **Integration registry entry** for `scribblevet` (auth_type per research finding).
3. **MCP tools** in `apps/mcp-server/src/mcp_tools/scribblevet.py`:
   - `scribblevet_list_recent_notes(date_range, dvm_id?)` — pull notes since last sync
   - `scribblevet_get_note(note_id)` — full SOAP body
   - `scribblevet_search(query, patient_id?)` — text search across notes
4. **Ingest workflow** — `ScribbleVet Note Sync`, cron every 15 min:
   - Calls `scribblevet_list_recent_notes(date_range='15m')`
   - For each note: `find_entities(name=patient_name, entity_type='patient')` → if missing, `create_entity` with signalment from the note
   - `record_observation` with `observation_type='clinical_note'`, the note's S/O/A/P sections in the text, and `source_type='scribblevet'`
   - Embed via `embed_text()` so semantic recall surfaces them
   - Tag the observation with `dvm_id` + `visit_date` so Clinical Triage can filter
5. **Integration with Clinical Triage Agent persona** — add an explicit instruction to call `search_knowledge` for prior `clinical_note` observations on the patient before drafting the intake summary, surfacing prior diagnoses + ongoing meds in the "PRIOR HISTORY" section of the template.
6. PR on `feat/scribblevet-integration`, assigned to nomad3, no AI credit lines.

## Scope — IN

- Read-only ingest from ScribbleVet → AgentProvision
- Per-tenant ScribbleVet credentials via `integration_credentials`
- Idempotency on `(tenant_id, note_id)` — re-syncing the same note doesn't duplicate observations
- Embedding for every ingested note
- Patient-entity creation if absent (signalment from note's history section)

## Scope — OUT

- Writing notes back into ScribbleVet
- Replacing ScribbleVet (Angelo wants to keep using it as the in-room scribe; we're connecting, not replacing)
- Real-time streaming (15-min cron is fine)
- DVM-side authoring tools (separate Phase 4 surface)

## Steps

1. **Research (week 1):** ScribbleVet's developer portal / API docs / webhook docs. Failing public docs, reach out to support@scribblevet.com requesting partner / API access. Document findings in `docs/research/2026-05-09-scribblevet-api-research.md`.
2. **Adapter scaffold (week 1, parallel to research):** Build against a mocked API surface based on common AI-scribe patterns (Heidi Health, DeepScribe). Three MCP tools + unit tests with fixtures.
3. **Ingest workflow (week 1):**
   - JSON definition: cron `*/15 * * * *` America/Los_Angeles
   - Steps: `scribblevet_list_recent_notes` → for-each loop → `find_entities` (or `create_entity`) → `record_observation` → embed
   - Idempotency key: `(tenant_id, scribblevet_note_id)`; check existence via `find_entities(entity_type='clinical_note_marker', name=note_id)` before insert OR add a unique constraint on `knowledge_observations.source_external_id`
4. **Activation gate:** workflow refuses to run until tenant configures ScribbleVet credentials.
5. **Clinical Triage persona update:** add the prior-history retrieval instruction.
6. **Pet Health Concierge persona update:** when a client asks record-aware questions, search clinical-note observations first via `search_knowledge`.
7. **Tests + PR.**

## Inputs / blockers

- ScribbleVet's partner-API access — the entire plan rests on this. If they refuse external API access, fallback options:
  - **Email-based ingest:** ScribbleVet emails the DVM a copy of the note → mailbox rule forwards to a clinic-billing@ inbox → AgentProvision ingests from email. Slower, lossier.
  - **Browser-extension scrape:** harder, brittle, ToS risk. Not recommended.
- Patient-entity disambiguation: if two clients both have a "Bella," need owner phone or pet-ID matching. ScribbleVet should expose patient_id we can pin entities to.

## Definition of Done

- ✅ Research doc under `docs/research/`
- ✅ Adapter + 3 MCP tools + unit tests green
- ✅ Ingest workflow definition + activation gate + idempotency
- ✅ Clinical Triage + Pet Health Concierge personas updated to reference clinical-note observations
- ✅ Manual end-to-end: ingest 1 sample note (real or mocked) → confirm observation lands on the right patient entity with embedding, and Clinical Triage retrieves it on the next intake summary
- ✅ PR assigned to nomad3, no AI credit lines

## Risks

- ScribbleVet may not have a public API (most AI scribe vendors don't). Email-fallback is the contingency.
- Patient-entity dedup across thousands of notes: needs a real strategy. Owner phone + pet name + species is usually unique inside one practice.

## Cross-references

- Discovery doc: `docs/plans/2026-05-08-veterinary-vertical-angelo-discovery.md` — ScribbleVet listed as Angelo's current AI scribe vendor (standalone, unintegrated)
- Pattern: BrightLocal adapter (PR #324) for the auth + cache shape
