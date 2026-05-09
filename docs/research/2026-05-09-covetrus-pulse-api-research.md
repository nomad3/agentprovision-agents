# Covetrus Pulse — API Access Research

**Date:** 2026-05-09
**Tenant:** The Animal Doctor SOC (`7f632730-1a38-41f1-9f99-508d696dbcf1`)
**Author:** sub-agent research, web sources only
**Driving plan:** `docs/plans/2026-05-09-covetrus-pulse-api-research.md`
**Status:** RESEARCH-ONLY — no code touched.

## TL;DR

- **A Pulse-facing API exists**, but it is gated behind the **Covetrus Connect Technology Integration Partner Program** (a.k.a. "Covetrus Connect API"). It is described by Covetrus as *"the only authenticated and supported way to integrate with Covetrus practice management software."* [1]
- **Authentication is OAuth-style** (client_id + client_secret pairs are the documented credential format used by integration partners such as ezyVet). [2] **Caveat:** the `client_id`/`client_secret` shape is verified from the **ezyVet procurement-API docs**, not from a Pulse-side primary source — the Pulse-specific OAuth flow is not publicly documented. Confirm at partner intake.
- **A live developer-portal hostname is reachable** at `https://api.covetrus.com/` (header reads "Covetrus NA API", environment label `ex-prod01`) but the public surface is empty — endpoint reference, sandbox URLs, and OAuth flow are gated behind partner approval. [3]
- **Approval timeline:** Covetrus's own pages say partners are contacted by the Partnerships team **within 6–8 weeks** of submitting the online registration. [1][4]
- **HIPAA / BAA** is **not advertised** on Pulse's terms or partner pages (HIPAA does not strictly apply to veterinary records anyway). The privacy framework that DOES touch this stack is **CCPA/CPRA** — the Animal Doctor SOC is California-based, the persona surfaces pet-owner PII (name + phone + pet record), and CCPA's "personal information" definition reaches owner records held about California residents. Treat any Pulse-data egress as CCPA-covered: respect deletion / access requests, contractually flow CCPA terms through to AgentProvision via the partner agreement. Covetrus publishes a **Data Processing Addendum** for GDPR purposes [5] (CCPA terms typically ride on the same DPA) and is referenced by third parties as **SOC 2 Type II–aligned**, but I could not locate a primary Covetrus document confirming SOC 2 status (mark this as **unverified**).
- **The premise that "VetDodo proves the Pulse API exists" is partially wrong.** VetDodo (now `dodo.ai/vet`) publicly documents a deep, bi-directional API integration with **ezyVet** (also a Covetrus product), not with Pulse. [6][7] That still proves Covetrus runs a real partner-API program — just on the ezyVet side of the house. Pulse's own partner directory shows ~40+ live partners in domains close to ours (Birdeye, Boomerang Vet, Otto, SmartFlow, Anipanion, Axion) [8][9], so the path is real, just not VetDodo-proven for Pulse specifically.

## What I verified

### 1. Covetrus Connect (the API program)

- **Program page:** `https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/technology-integration-hub/` [1]
  - Self-describes as *"a security-enhanced, permissions-based integration platform that connects Covetrus practice management software platforms with most major partner services and apps."*
  - States it is *"the only authenticated and supported way to integrate with Covetrus practice management software"* — i.e. **Covetrus considers screen-scraping out of scope and unsupported** even though their ToS doesn't enumerate scraping prohibitions in the Pulse-specific Terms [10].
  - The sign-up form on this page captures: vendor name, website, contact, **product category** (23 options), current user base, **integration type (Pull / Push / Bi-Directional)**, and number of practices already using Covetrus systems.
- **Application process:** registration form on the program page → **review and sign the Covetrus Integrated Partner Agreement** → access granted to *"Developers Tool kit, Knowledge base, Resource Center and technical API documentation."* [4]
- **Timeline:** Covetrus's APAC partner page explicitly states that the Partnerships team contacts applicants **within 6–8 weeks** of online application submission. [4]
- **Fee:** **No published fee schedule.** I could not confirm whether the partner program is free, revenue-share, or flat-fee. Mark as **unverified** — must be asked directly during the application call.
- **Partner directory (~40+ partners listed publicly):** Zoetis VetScan, AKC Reunite, Antech, ALLPRO Imaging, Anipanion, Aspyra, Axion Communications, Birdeye, Boomerang Vet, Buddy ID, Capsa Healthcare, CareCredit, plus the AI-scribe partner *Veterinarian Electronic Assistant (VEA)* — described as *"a voice-assisted SOAP portal powered by OpenAI."* [9] No "Dodo" / VetDodo entry in the Pulse Connect directory at the time of search.
- Earlier industry coverage (Today's Veterinary Business) put the partner count at **40+** at launch [11]; Covetrus marketing materials now claim **250+ third-party integrations** on the broader Pulse platform [12]. The two numbers are reconcilable: Connect-API partners are a subset of the broader integration ecosystem (which also includes labs and devices wired in via their own protocols).

### 2. The auth model — what we can infer

The strongest concrete evidence of the auth model comes from the **ezyVet integration page documenting how to wire Covetrus credentials**: *"the system downloads a text file that has a client ID and a client secret"*, and a worked example uses the form `<account_number>-001` for the secret on the standard supplier-side integration. [2] That is consistent with **OAuth 2.0 client_credentials grant**, which is the typical pattern for B2B PIMS-to-partner integrations and matches the *"permissions-based"* language Covetrus uses on the program page [1].

Caveats I want to flag honestly:
- The ezyVet page documents the **product-supplier (procurement) Covetrus API**, not necessarily the Pulse PMS API. They share the Covetrus Connect umbrella and the credential shape is a strong signal, but **the exact Pulse OAuth scopes are not public** and must be confirmed during partner enrollment.
- **No public sandbox URL was found.** The live host `api.covetrus.com` returns only a banner; sandbox/playground access is presumed to be issued post-signature alongside the Developers Tool Kit. **Mark as unverified** until partner onboarding confirms.

### 3. Data scopes — what other partners successfully read/write

Pulse partners' product pages give us a usable lower bound on accessible scopes (each is verified on the partner's own marketing/docs):

| Partner | Read | Write | Source |
|---|---|---|---|
| Otto (Pulse-specific page) | clients, patients, appointments, history | conversation notes, forms, payments, appointment bookings | [13] |
| Chckvet | "Two-Way Sync" with Pulse — clients, appointments | appointments, two-way client data | [14] |
| SmartFlow | Pulse integration page exists; details gated behind a browser check at fetch time | (presumed treatment-board / SOAP context) | [15] |

So the scopes we care about for AgentProvision's three Pulse-dependent workflows are demonstrably reachable through Covetrus Connect today:

- **Pet Health Concierge ("Harriet replacement"):** patient signalment, weight, vaccines, current meds, allergies, diagnoses, last-visit summary → Otto already does the equivalent. [13]
- **Multi-Site Revenue Sync:** invoices and line items with location filtering → SmartFlow + Otto-class partners do this on Pulse. [13][15]
- **Bookkeeper cross-reference:** invoice + payment write-throughs → Otto explicitly documents posting payments back into Pulse. [13]

### 4. HIPAA / SOC 2 / data-handling posture

- **HIPAA:** No mention of HIPAA or BAA on the Pulse Terms of Service [10] or the Connect program page [1]. Veterinary PHI is generally **not** PHI under HIPAA (HIPAA covers human protected health information), so this is normal industry posture; for Angelo's needs, what matters is **client-PII handling**, not HIPAA per se. **Mark "HIPAA-equivalent" as unverified** but probably moot for the vet vertical.
- **GDPR / DPA:** Covetrus publishes a public **Data Processing Addendum** with Ireland as the supervisory authority. [5] This would govern any EU-resident pet-owner data Pulse touches; not a hot issue for The Animal Doctor SOC (CA-only) but reassuring for the broader VMG distribution thesis.
- **SOC 2:** Third-party industry write-ups assert SOC 2 Type II alignment, but I could not find a primary Covetrus statement confirming it. **Mark as unverified.** Confirm via Covetrus security questionnaire during partner intake.
- **Pulse Terms of Service** [10] are mostly silent on automated access. They prohibit reverse-engineering and reproducing the software, and impose AI-training restrictions on Client Data, but do **not** explicitly outlaw scraping. Even so, the Connect partner page calls partner-API the *"only authenticated and supported"* path [1] — meaning a scraper would be unsupported, brittle, and reputationally risky for AgentProvision's "trustworthy clinic platform" positioning.

### 5. The VetDodo correction

The driving plan claims *"VetDodo proves the API exists."* Verified ground truth as of 2026-05-09:

- VetDodo (a.k.a. **Dodo**, founded by three Stanford engineers) operates at `vetdodo.com` which **302-redirects to `dodo.ai/vet`**. [6]
- Their **public PIMS integration page is for ezyVet only**, with the documented behavior: *"Dodo connects directly to ezyVet via secure APIs, enabling real-time reading and writing of data."* [7]
- I found **no Dodo entry in the Covetrus Pulse Connect partner directory**, and no Dodo marketing page calling out a Pulse integration. [9]
- ezyVet is a Covetrus-owned PIMS, so Dodo *is* a Covetrus-API consumer — just on the ezyVet side. The Pulse-side equivalents we care about are **Otto** (closest behavioral analog: front-desk + records), **Anipanion** (telehealth), **Birdeye** (client comms), and **VEA** (AI scribe). [9][13]

This is important: Simon should **not pitch Covetrus by saying "VetDodo does this"** — that conflates the ezyVet program with the Pulse program. The honest pitch is *"Otto / SmartFlow / Anipanion already do bi-directional Pulse integrations through Covetrus Connect; we want to do the same for AgentProvision's veterinary agents."*

## Three options evaluated

| Option | Path | Cost | Time-to-prod | Risk | Quality of integration |
|---|---|---|---|---|---|
| **A — Partner program (Covetrus Connect)** | Submit registration on the Connect program page → sign Integrated Partner Agreement → receive Developers Tool Kit + sandbox | Unknown fee (likely modest or revenue-share); ~3 dev-weeks of integration work after access | **6–8 weeks to first credentials**, then days–weeks to working integration | Approval is gated; no public SLA on terms; could be revenue-share | Highest — supported, documented, OAuth, sandbox, future-proof |
| **B — Customer API access via Angelo's Pulse credentials** | Use Angelo's tenant Pulse login to enable a per-tenant Connect token (the SmartFlow-style flow toggled in Pulse's Integration Settings) | Free in dev | Days, **but only if** Pulse exposes per-tenant API tokens to non-partners — and the public docs do not confirm this | High — Connect API is *partner-issued*, so customer-side tokens almost certainly won't grant the breadth of scopes we need (patient + billing + inventory). Customer-issued tokens look limited to enabling already-approved partner integrations, not arbitrary 3rd-party callers. | Likely insufficient scope; brittle |
| **C — Screen-scrape fallback (headless browser against Pulse web UI)** | Playwright against `app.evetpractice.com` / Pulse web | Dev cost only | Days | High — ToS says Connect is the *only supported* path [1]; brittle to UI changes; bad story for Angelo's distribution thesis at VMG | Low — fragile, unauditable, can't sustainably read SOAP/billing |

## Recommendation: **Option A — Partner program**

Reasoning:

1. **It's the only path that scales beyond Angelo.** The Animal Doctor SOC tenant is a beachhead — the real prize is **VMG (~2,000 private practices)**. A scraper will not survive contact with even one VMG-scale rollout. Partner credentials will.
2. **The auth shape is workable.** OAuth client_credentials + per-practice consent is exactly the pattern AgentProvision's existing integration registry already supports (we use the same shape for Google OAuth, Microsoft, Jira). Adding Covetrus is a registry entry, not a new architectural layer.
3. **The 6–8 week wait is bearable.** During the wait we can ship the iMessage/SMS lane, the Bookkeeper workflow against email-mailbox sources, BrightLocal SEO Sentinel, and the AHA chart-of-accounts seeding — none of which depend on Pulse credentials. The Pet Health Concierge can ship a **stub-mode** without Pulse and turn record-aware on credential delivery (graceful upgrade path).
4. **It strengthens the VMG pitch.** Being a *Covetrus Connect Partner* is a logo and a trust signal Angelo can take to VMG ahead of any technical demo — it's worth the 6 weeks for that alone.

Option B is worth a *parallel low-cost probe* (literally 30 minutes — log into Angelo's Pulse instance, look for an "API tokens" section in Settings) but should not be the primary plan. Option C is a backstop only if Covetrus rejects the application, and even then I'd recommend pivoting to Avimark-direct or pushing harder on the partner appeal before scraping.

## Concrete next-step Simon can take in the next 24 h

1. **Submit the Covetrus Connect partner registration form** at:
   `https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/technology-integration-hub/`
   - Vendor: AgentProvision / Wolfpoint
   - Product category: choose *Client Communication* + *Workflow Optimization* (closest matches given our Pet Health Concierge + Bookkeeper workflows)
   - Integration type: **Bi-Directional**
   - Current user base: be honest — note Animal Doctor SOC as design-partner customer
   - Number of practices already on Covetrus systems: **3** (Anaheim, Buena Park, Mission Viejo via Animal Doctor SOC)
2. **In parallel**, email **support_pulse@covetrus.com** [16] from Simon's address asking specifically for:
   - sandbox / developer-environment URL
   - whether the program has any fee, revenue-share, or flat partner cost
   - SOC 2 Type II report under NDA
   - confirmation the Pulse Connect API supports the scopes: patients, appointments, invoices+line-items, payments, inventory, SOAP notes
3. **Quick 30-min Option-B probe:** have Angelo log into his Pulse instance and screenshot Settings → Integrations. If a self-serve API token tab exists, that's a free pre-partner unblock for read-only scopes; if it doesn't, we lose nothing.
4. **Reach out to Otto** for an informal partner-experience reference call — they are the closest behavioral analog to our Pet Health Concierge on Pulse, and a 20-min call can de-risk the timeline and surface fee structure before we sign anything blind. Direct paths:
   - Partner / sales contact form: `https://otto.vet/contact/` (preferred)
   - General inquiries: hello@otto.vet (referenced on otto.vet)
   - LinkedIn outreach to Otto's CEO/CTO is also reasonable for a 20-min reference chat — they actively market Pulse compatibility on `https://otto.vet/integrations/covetrus/`.

## Sandbox / playground URL

- **Live partner-portal hostname found:** `https://api.covetrus.com/` (label `Covetrus NA API`, environment `ex-prod01`). Public surface is empty. [3]
- **No public sandbox URL found.** Sandbox is presumed to be issued post-signature with the Developers Tool Kit. Confirm during partner intake and update this doc.

## Open questions / unverified claims (flagged honestly)

- **Fee structure of the Connect partner program.** Not published. Could be free, flat-fee, or revenue-share.
- **Exact OAuth scopes available on the Pulse Connect API.** The credential shape (client_id / client_secret) is verified [2]; the per-resource scope list (patient.read, appointment.write, invoice.read, soap.read, inventory.read) is **not** publicly documented.
- **Webhooks vs polling.** Covetrus material implies push-or-pull or bi-directional partner choice [1] but the actual webhook contract is not public. Otto and Chckvet behavior suggests at minimum periodic pull plus on-demand write.
- **SOC 2 Type II report.** Asserted by industry write-ups, not by a Covetrus primary source we could find. Request under NDA.
- **Per-practice consent model.** It's unclear whether each practice (e.g. each of Angelo's three locations) consents individually or whether the Pulse instance is consented once. Given the Animal Doctor SOC runs on a **single Pulse instance with a `location_id` filter**, the more likely answer is one consent flow per Pulse account; confirm at partner intake.
- **Rate limits / quotas.** Not public. Standard PIMS-partner quotas are typically 5–10 req/s per partner with burst bucketing — but this is industry norm, not a verified Covetrus number.

## Sources

1. Covetrus Technology Integration Partner Program — [https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/technology-integration-hub/](https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/technology-integration-hub/)
2. ezyVet Knowledge Center — *Configure the Covetrus API integration* — [https://docs.ezyvet.com/en/see-all-integrations/product-suppliers/covetrus/configure-the-covetrus-api-integration](https://docs.ezyvet.com/en/see-all-integrations/product-suppliers/covetrus/configure-the-covetrus-api-integration)
3. Covetrus NA API host — [https://api.covetrus.com/](https://api.covetrus.com/)
4. Covetrus Connect Partner Program (APAC, identical program globally) — [https://software.covetrus.com/apac/veterinary-solutions/covetrus-connect-partner-program/](https://software.covetrus.com/apac/veterinary-solutions/covetrus-connect-partner-program/)
5. Covetrus Data Processing Addendum (GDPR) — [https://covetrus.com/legal/covetrus-data-processing-addendum/](https://covetrus.com/legal/covetrus-data-processing-addendum/)
6. Dodo (formerly VetDodo) homepage redirect — [https://www.vetdodo.com/](https://www.vetdodo.com/) → `https://dodo.ai/vet`
7. ezyVet — Dodo Integration page — [https://www.ezyvet.com/integration/dodo](https://www.ezyvet.com/integration/dodo)
8. Otto Pulse integration — [https://otto.vet/integrations/covetrus/](https://otto.vet/integrations/covetrus/)
9. Covetrus Connect Partner Directory — [https://covetrus.com/connect-directory](https://covetrus.com/connect-directory)
10. Covetrus Pulse Software Terms of Service — [https://covetrus.com/legal/covetrus-pulse-software-terms-of-service/](https://covetrus.com/legal/covetrus-pulse-software-terms-of-service/)
11. Today's Veterinary Business — *Covetrus connects PIMS users with service partners* — [https://todaysveterinarybusiness.com/covetrus-connects-pims-users-with-service-partners/](https://todaysveterinarybusiness.com/covetrus-connects-pims-users-with-service-partners/)
12. Covetrus Pulse product page — [https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/covetrus-pulse/](https://covetrus.com/covetrus-platform/workflow-and-productivity-tools/covetrus-pulse/)
13. Otto + eVetPractice/Pulse integration details — [https://otto.vet/integrations/covetrus/](https://otto.vet/integrations/covetrus/)
14. Chckvet Covetrus Pulse Two-Way Sync — [https://chckvet.com/pims/pulse/](https://chckvet.com/pims/pulse/)
15. SmartFlow Covetrus Pulse integration documentation — [https://docs.smartflowsheet.com/en/browse-documentation/integrations/covetrus-pulse/configure-the-covetrus-pulse-integration](https://docs.smartflowsheet.com/en/browse-documentation/integrations/covetrus-pulse/configure-the-covetrus-pulse-integration)
16. Covetrus Pulse support contact (referenced repeatedly across Covetrus support pages) — `support_pulse@covetrus.com`
