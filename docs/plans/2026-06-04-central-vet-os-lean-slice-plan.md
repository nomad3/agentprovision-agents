# Central Veterinary OS — lean first slice plan

**Date:** 2026-06-04
**Branch:** `vet-os/central-os-foundation`
**Task:** #22
**Status:** plan — extractor build in progress; pending Luna review

## The OS (one provisioner, two variants)

Brett (cardiology specialist) and Angelo (GP) are **two `provision_vet_practice(tenant_id, variant)` configs** over the already-shipped spine (`vet_practice.py` + `vet_manifest.py`, PR #740), sharing one KG, credential vault, dynamic-workflow executor, and Luna supervisor. `cardiology_v1` ships today (5 agents). The OS is realized by registering a `gp_full` variant (lift the 5 GP personas from `seed_animaldoctor_agent_fleet.py`). **Config, not new code** — the provisioner is generic + idempotent.

## Lean first slice (build-now, zero PIMS)

Brett's **cardiology referral-report loop**: Gmail-in → extract → draft → human approval → Drive doc + email-back. Only **4 genuinely net-new code pieces**; the rest is wiring existing infra (`human_approval` durable backend, `send_email`, KG persistence, the Cardiac Report Generator template).

Net-new (this plan):
1. **Deterministic echo-table extractor** — text-anchored parser of the "Adult Echo: Measurements and Calculations" block. Real format (machine export): multi-column text, up to 3 `label value unit` triples/line; **`extract_tables()` does NOT capture it** — must parse text. Split PDF→text (pdfplumber) from text→measurements (pure, unit-testable).
2. **Measurement-QA contract** — `Measurement{field,label,value,unit,modality,source_page,confidence,outlier_flag,outlier_reason}` + `EchoExtraction`. Outlier rules (Luna + ACVIM MMVD consensus, JVIM 2019 33(3):1127): `LA:Ao ≥1.6 or <0.8 ⇒ review`; `LVIDdN ≥1.7 ⇒ review`; `FS% <25 or >55 ⇒ review`. Derived **LVIDdN = LVIDd(cm)/weight(kg)^0.294** computed when both inputs exist. We **never auto-conclude a stage** — at/above B2 thresholds we *escalate to clinician review* (staging also needs murmur grade/VHS).
3. **Completeness gate** — block draft if LVIDd / LVIDs (or FS/EF) / LA:Ao / species / weight missing or LOW confidence. **Species** is inferred from explicit dog/cat signal or a known breed map; an **unknown breed leaves species unset** (forces human confirm) — never default unknown→canine.
4. **Approval-review surface** — interim = existing dashboard run-detail; polished surface pending operator pick.

Wire existing (later steps): reshape Cardiac Report Generator template (`extract_echo_structured → generate_dacvim_report → human_approval → send_email`); KG case-artifact persistence; `download_attachment` per-page/bytes contract change (one line, at integration time).

## Build sequence

1. **(now)** Extractor + QA contract + completeness gate, prototyped + tested against the on-disk Winnie machine export (no Gmail/tenant/UI needed — Luna's "start here"). → `apps/api/app/services/vet/echo_extractor.py` + tests.
2. Luna review of the extractor (her platform).
3. Reshape the workflow template (split step + insert human_approval + send_email + KG persist).
4. Provision the demo tenant (`cardiology_v1`) + enable Gmail/Drive/Calendar.
5. `download_attachment` bytes contract + integration test against a real Gmail-delivered PDF.
6. Approval-review surface (the one the operator picks).

## Decisions (proceeding on these defaults; operator can override)

- **Tenant:** fresh BB Cardiology Demo (Luna + provisioner-plan both recommend).
- **Scope:** cardiology-only loop (GP daily value is Pulse-gated).
- **PIMS:** keep Covetrus Pulse partner application moving (~late-June credentials); exploration, not a dependency.
- **Approval surface:** interim dashboard run-detail; polished surface = operator's call (last step, non-blocking).

## Build-now vs explore-later

**Build now:** cardiology loop end-to-end; provisioner seeding; extractor/QA/gate; human_approval + send_email + KG persist; Gmail/SMS comms scaffolds; gp_full manifest registration (config-ready, daily-loop value Pulse-gated).

**Explore later (PIMS status):** Covetrus Pulse — *application in progress*, partner-approval-blocked, ~late-June creds (keep moving). ScribbleVet — *research-gated*, no confirmed public API, email-ingest fallback. Imaging/DICOM, labs (IDEXX/Antech), other PIMS (ezyVet/Cornerstone/…), pharmacy/controlled-substance, iMessage (Apple-approval-gated; SMS interim), PIMS writeback — Phase 3.

## Risks

- **Attachment-byte corruption** — on-disk prototype won't catch a byte-mangling `download_attachment`; verify at integration test vs a real Gmail PDF.
- **Echo-layout brittleness** — parser built against one export; keep it **label-anchored, not positional**; require a 2nd export pair before production.
- **Soft safety floor** — for v1 the enforced floor is `human_approval` + user-principal `AgentPermission` only. **`human_approval` is UNCONDITIONAL before `send_email`** — every report is human-approved; `needs_review` only *escalates/decorates* the approval (a flagged banner + review reasons), it never bypasses it when False (Luna clinical review). `_DIAGNOSTICS_VALUES` are **audit metadata**, not runtime-enforced (`value_arbitration.py` is pure-library). Rejection/timeout must be wired to a `condition` that structurally halts `send_email`. Be honest; harden before multi-specialty scale.
- **Thin RAG corpus** — only Winnie + MR B2 template; first-case draft quality may be weak; get 2-3 more real cases.

## Open questions for operator + Luna

1. Confirm tenant (fresh BB Cardiology vs reuse).
2. **Approval surface** — the genuine UX call; blocks the polished review UI (build only the chosen one).
3. Confirm cardiology-only lean scope.
4. Keep Covetrus partner application moving now? (default yes)
5. Register `gp_full` manifest now (config-ready) or defer to Pulse creds?
6. Provide 1 more finalized-report + machine-export pair (parser layout-tolerance) + 2-3 cases for RAG.
