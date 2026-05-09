# Plan — AAHA-Native Bookkeeper Export Formats (CPA-Software Agnostic)

**Owner:** Bookkeeper Agent backend + export-format adapters
**Tenant:** The Animal Doctor SOC (`7f632730-1a38-41f1-9f99-508d696dbcf1`); generalizes to every VMG tenant
**Why:** PR #321 seeded the 88-leaf AAHA chart of accounts. The Bookkeeper Agent categorizes line items against it. But today the only output is XLSX — Angelo's CPA may use any of QuickBooks, Xero, Sage Intacct, FreshBooks, or Wave. AAHA is the universal standard *every* VMG-member CPA understands; pinning to one accounting platform locks us into one CPA per tenant. The right architecture: **AAHA stays canonical; format adapters convert AAHA-categorized output to whatever the CPA imports.**

## Goal

Ship multi-format export so the Bookkeeper Agent's weekly output is consumable by any of the major small-business accounting platforms via a `tenant_features.cpa_export_format` config. AAHA stays the source of truth.

## Deliverables

1. **Per-tenant config field** — add `cpa_export_format` column to `tenant_features` (default `'xlsx'`), migration 117.
2. **MCP tool** in `apps/mcp-server/src/mcp_tools/bookkeeper_export.py`:
   - `bookkeeper_export_aaha(tenant_id, period_start, period_end, format=None)` — pulls categorized observations, runs them through the format adapter selected by `format` arg or `tenant_features.cpa_export_format`, returns a binary blob + filename + MIME type.
3. **Format adapter modules** under `apps/api/app/services/bookkeeper_exporters/`:
   - `xlsx.py` — current format; AAHA tab + per-location tabs + flagged-for-review tab + vendor summary tab. (Already implemented; refactor into the adapter shape.)
   - `csv.py` — generic flat CSV with columns `date, vendor, amount, gl_code, aaha_category, location, confidence, source_email_id`. Importable into anything.
   - `quickbooks_iif.py` — Intuit Interchange Format (legacy QuickBooks Desktop). Header lines + transaction blocks per QuickBooks's published IIF spec.
   - `quickbooks_qbo.py` — QuickBooks Online importable bank-statement CSV format (different from generic CSV — column order and naming matter).
   - `xero_csv.py` — Xero's bank-statement CSV format (date / amount / payee / description / reference / cheque-number).
   - `sage_intacct_csv.py` — Sage's GL-import CSV (simpler than IIF; based on Intacct's published template).
   - Each adapter: takes `List[CategorizedLineItem]` + `AAHATaxonomy` + `tenant_metadata` → returns `(bytes, filename, mime_type)`.
4. **Workflow update** — `Bookkeeper Categorization` workflow's final delivery step calls `bookkeeper_export_aaha` (no explicit format → reads tenant_features), attaches the resulting file to the email Luna sends to owner + Taylor + CPA.
5. **Integration UI** — `/integrations` page exposes a "CPA software" dropdown per tenant that writes to `tenant_features.cpa_export_format`.
6. **Round-trip test fixtures** — sample week of 30 line items, run through every adapter, assert each format parses correctly via the canonical importer (e.g. `quickbooks-iif-parser` npm pkg for IIF validation).
7. PR on `feat/aaha-export-formats`, assigned to nomad3, no AI credit lines.

## Scope — IN

- AAHA chart of accounts stays the canonical layer (PR #321 already seeded it; this PR doesn't touch the taxonomy)
- 6 export adapters: XLSX, CSV, QB IIF, QB Online CSV, Xero CSV, Sage Intacct CSV
- Per-tenant config — single `cpa_export_format` field, default XLSX
- Tests covering at minimum schema validity (parser doesn't reject the file) for each format
- Bookkeeper workflow picks format dynamically based on tenant config

## Scope — OUT

- Direct API write into accounting platforms (push-to-QB Online API). Phase 2 — once a tenant explicitly opts in.
- AI-driven CPA detection ("which software does the CPA use?") — Simon configures it manually for now.
- Tax prep / 1099 generation — the CPA still runs final tax workflows.
- Locale-specific formats (Australian Xero, Canadian Sage variants) — defer until a tenant requests it.
- Re-categorization or AAHA edits — that happens in the Bookkeeper Agent's main flow.

## Steps

1. **Migration 117 (idempotent, self-recording):** add `cpa_export_format VARCHAR(32) DEFAULT 'xlsx'` to `tenant_features`. Tenant-agnostic.
2. **Refactor existing XLSX exporter** in `apps/api/app/services/bookkeeper.py` (or wherever it lives today) into `apps/api/app/services/bookkeeper_exporters/xlsx.py` with the adapter signature. Existing behavior preserved.
3. **Build CSV adapter** — flat, generic. The simplest one; ship first as the baseline.
4. **Build QuickBooks IIF adapter** — Intuit publishes the IIF spec. Header lines: `!ACCNT`, `!TRNS`, `!SPL`, `!ENDTRNS`. Transaction blocks per AAHA category mapped to a GL code.
5. **Build QuickBooks Online CSV adapter** — different column conventions from IIF. Documented at quickbooks.intuit.com.
6. **Build Xero CSV adapter** — Xero's bank-statement CSV: `*Date, *Amount, Payee, Description, Reference, Cheque Number`. Stars are Xero-required.
7. **Build Sage Intacct CSV adapter** — Sage's GL-journal-entry CSV.
8. **Wire MCP tool** `bookkeeper_export_aaha` — looks up `tenant_features.cpa_export_format`, dispatches to adapter, returns bytes + filename + MIME.
9. **Update Bookkeeper Categorization workflow** — replace the existing `generate_excel_report` step with `bookkeeper_export_aaha`. The deliver step attaches the file to email + WhatsApp.
10. **Web UI** — Integrations panel adds a dropdown for `cpa_export_format` (XLSX / CSV / QuickBooks IIF / QuickBooks Online / Xero / Sage Intacct).
11. **Round-trip tests** — fixture week → each adapter → schema validation.

## Definition of Done

- ✅ 6 adapters, each with at least one unit test that round-trips a fixture and validates the output schema
- ✅ Migration 117 applied + self-recorded
- ✅ Web UI dropdown live; changing it changes the next weekly export
- ✅ Bookkeeper Categorization workflow swapped to dynamic-format export
- ✅ Animal Doctor SOC tenant: confirm the default XLSX still works exactly as it did before this PR (no regression)
- ✅ PR `feat/aaha-export-formats`, assigned to nomad3, no AI credit lines

## Risks

- Adapter-format edge cases (Xero rejects rows with unbalanced debits/credits if the import path expects a journal entry rather than a statement) — schema-validate tests catch this.
- IIF is legacy; QB Desktop is shrinking in the SMB market. Worth the effort because it's also the format CPAs export from older systems. QBO CSV is the more common path going forward.
- AAHA → GL-code mapping can be 1:N — one AAHA leaf may correspond to multiple GL codes per CPA's chart. The mapping table lives in the YAML (PR #321) with a single GL code per leaf; if a CPA needs different mappings, expose a tenant-level GL-code override map.

## Cross-references

- AAHA seed: `apps/api/scripts/seed_aha_chart_of_accounts.py` + `docs/data/aha-chart-of-accounts/2026-05-09-canonical-taxonomy.yaml` (PR #321)
- Bookkeeper Agent persona: in DB, agent name "Veterinary Bookkeeper Agent"
- Workflow definition: `dynamic_workflows.name = 'Bookkeeper Categorization'`
- Discovery context: `docs/plans/2026-05-08-veterinary-vertical-angelo-discovery.md` — Angelo's CPA pain replaces the $1k/mo human bookkeeper
