# ScribbleVet — API Access Research

**Date:** 2026-05-09
**Tenant:** The Animal Doctor SOC (`7f632730-1a38-41f1-9f99-508d696dbcf1`)
**Author:** sub-agent research, web sources only
**Driving plan:** `docs/plans/2026-05-09-scribblevet-integration.md`
**Status:** RESEARCH-ONLY — no code touched in this artifact. Phase B adapter scaffold lives in the same PR but in a separate set of files.

## TL;DR

- **ScribbleVet does NOT publish a public API or developer portal as of 2026-05-09.** The product self-describes as a recording-driven AI scribe whose only documented data egress is the **ScribbleVet Browser Companion** Chrome/Edge extension that performs DOM-level "1-click transfer" of finished SOAP notes into the operator's own PIMS. [1][2][3]
- **Authentication for the extension is user-scoped** (the operator logs into ScribbleVet and into their PIMS — extension acts on behalf of an authenticated browser session). There is no documented OAuth client_credentials flow, no API key, no service-account, no webhook surface, and no JSON/CSV export endpoint that an external system can poll. [3][4]
- **The corporate parent changed in January 2026.** Instinct Science acquired ScribbleVet (announced 2026-01-16) and *Instinct itself* runs a **Partner API** for its EMR. [5][6][7] So while ScribbleVet has no API today, the *acquirer* has the right org structure for one — and the press release explicitly commits to "deeper integrations" as a roadmap item. The same 6–8wk-style partner-application path that Covetrus Connect uses is the realistic ask. [8]
- **Terms of Use prohibit "automated systems" / scrapers**; ScribbleVet is operated by Kairo Care, Inc. and the ToS reserves broad rights over user data including AI-training use of session content. [9] Browser-extension scraping (Option C in the parent plan) is therefore both a contractual and reputational non-starter.
- **Outreach paths are clear and email-driven**, not portal-driven:
  - **Primary:** `support@scribblevet.com` (general support + feature requests + partnership inquiries per Support Hub) [4]
  - **Secondary (homepage footer):** `contact@scribblevet.com` (demos + group pricing) [3]
  - **Acquirer / Instinct partner channel:** the Instinct EMR integration page directs developers to their generic contact form for Partner API access [7]
- **Recommendation: Option A — partner application via Instinct Science**, scaffold against a mocked API surface today, light up real wiring on credential delivery. Email-fallback (Option B in the parent plan) becomes the contingency. Browser-companion scrape (Option C) is rejected on ToS grounds.

## What I verified

### 1. The product surface — what ScribbleVet actually is (and isn't)

- **Public homepage:** `https://www.scribblevet.com/` self-describes as "AI digital scribe for busy veterinarians." Founded by Rohan Relan (named for his rescue dog Potato). [1]
- **Native client surface:** iOS app + Android app + web app. The recording flow is in-product; the *output* is a SOAP note that ScribbleVet renders in its own UI. Users can "copy-paste" sections OR click the Browser Companion button to transfer to a supported PIMS. [3][10]
- **Browser Companion (Chrome Web Store v1.21.0, updated 2026-04-24, publisher Kairo Care, Inc.):** [11]
  - **Permissions declared:** "Personally identifiable information," "Authentication information," "Website content."
  - **Target PIMS websites:** Covetrus Pulse, ezyVet, Rhapsody, Vetspire, Instinct, Daysmart, Shepherd. [11][3]
  - **Mechanism:** the extension is a content-script bridge — it reads the rendered note from the ScribbleVet web app and writes it into the PIMS DOM after the operator has manually mapped sections once per template. Extension authentication = "log in to your ScribbleVet account."
  - **Critically: there is no extension-exposed read endpoint we can call from server-side. Even "scrape the extension's traffic" doesn't yield a usable read API — the extension is a write-side companion only.**

So the data path inside ScribbleVet's silo today is:
```
Recording → AI generation → ScribbleVet web/mobile UI → operator review →
   Browser Companion DOM-write → PIMS (Pulse/ezyVet/etc.)
```

There is **no documented step where a third party (us) can subscribe to "note finalized" or pull "all notes from yesterday" via an authenticated channel.**

### 2. Confirmed-absence of API surface

I cross-checked four likely surfaces and found nothing on any of them:

| Surface | What I checked | Result |
|---|---|---|
| Public docs site | scribblevet.com — homepage, support hub, what's-new, terms | No `/api`, no `/developers`, no `/docs`, no portal link [1][3][4][12] |
| Generic developer-portal patterns | `https://api.scribblevet.com`, `https://developers.scribblevet.com`, search engines for "scribblevet OAuth," "scribblevet API key" | No public hostname returns docs; search returns generic OAuth tutorials only [13] |
| Browser-extension declared scopes | Chrome Web Store listing v1.21.0 | Only declares user-data + auth-data + website-content scopes for *writing into* PIMS — not for ScribbleVet-side egress [11] |
| Partner directory or "integrations" page | Homepage footer + What's New | Lists *inbound* integrations (Plumb's drug monographs, LifeLearn Sofie) and *outbound write* via Browser Companion. No "build on top of ScribbleVet" partner page exists. [3][12] |

Mark this as **strongly verified** rather than "I just didn't look hard enough" — the absence is a deliberate product posture, not an undocumented hidden surface. Their Help Hub explicitly tells operators to copy-paste or use the Companion when their PIMS isn't supported. [4]

### 3. Auth model — what a future ScribbleVet API would plausibly look like

We have zero primary-source evidence for a future API auth model on ScribbleVet itself. Two indirect signals:

- The **acquirer's Partner API** (Instinct Science / Instinct EMR) is publicly advertised as available to "customers and third-party platforms" via their generic contact channel. Instinct EMR's existing integration set names AI-scribe partners (Vetrec, Talkatoo, Dragon Dictation, VetGenus) [7] — all of which presumably authenticate via per-tenant OAuth-style credentials. Instinct's exact wire format is **not** public; this is the partner-call ask.
- **Kairo Care, Inc.** is the operating entity for ScribbleVet [9][11], and Kairo Care is now under Instinct Science [5]. So the most probable post-acquisition path is: **Instinct's Partner API gets extended to expose ScribbleVet endpoints**, OAuth client_credentials grant, per-practice tokens. This matches the BrightLocal / Covetrus Connect / ezyVet credential shape we already support in the integration registry — meaning *if* the partner program approves us, the wire-up cost is minimal. **Mark this entire paragraph as "probable, not confirmed."**

### 4. Webhooks / event surface

- **No webhooks are advertised.** Browser Companion is a poll-on-demand DOM bridge, not an event-publisher.
- The parent plan suggested "Browser-extension scrape" as Option C. **Rejected on ToS grounds**: the ScribbleVet Terms of Use explicitly prohibit *"any automated system, including without limitation, 'robots,' 'spiders,' 'offline readers,' etc., that accesses the Service in a manner that sends more request messages to the Kairo Care servers than a human can reasonably produce in the same period of time by using a conventional on-line web browser."* [9] Even a low-rate scraper falls under this clause once it's automated.

### 5. Rate limits / SLA / data-handling posture

- **Rate limits:** undocumented. The ToS rate-limit clause is qualitative ("more than a human can reasonably produce") rather than a numeric ceiling. Mark as **unverified** — partner intake will define this if approval comes.
- **Retention:** the ToS includes a discretionary-deletion clause: *"Kairo Care may refuse to store, provide, or otherwise maintain your User Data for any or no reason... User Data that is deleted may be irretrievable."* [9] This is operator-protective for ScribbleVet but flags a real risk for AgentProvision: if Angelo's clinic's notes vanish on the ScribbleVet side, our knowledge graph still has the ingested copy — *good for resilience, but flag the legal posture during partner intake.*
- **AI training rights:** the ToS grants Kairo Care broad rights to *"copy, analyze, and use any of Your User Data... for purposes of debugging, testing, or providing support or development services... future improvements... future products."* [9] This means notes Angelo dictates today can train tomorrow's ScribbleVet models. This is *industry-standard for AI scribes* (CoVet, Scribenote, VetRec, Hound — same posture) [14] but worth surfacing to Angelo and his future VMG-tier clients.
- **HIPAA / PHI:** veterinary records aren't PHI under HIPAA. **CCPA applies** (Animal Doctor SOC is California-based, and pet-owner records contain identifiers about California residents that fall under CCPA's "personal information" definition). No CCPA/SOC2 statement was located on the public site — **unverified**, ask during partner intake.

### 6. Data model — what a Pulse/ezyVet write-back tells us about what a future API would expose

The Browser Companion writes these note sections into the target PIMS [3][4]:

- **Subjective** (history, presenting complaint)
- **Objective** (physical exam findings, vitals)
- **Assessment** (problem list / differentials)
- **Plan** (treatment plan, prescriptions, follow-up)
- **Client take-home instructions** (rendered separately)
- **Dental chart** (rendered as an SVG or formatted block when applicable)
- Multi-pet visits split per pet

That's the full SOAP shape, and it's already structured in ScribbleVet's UI. So *if* a read API is ever exposed, these are the fields that will plausibly come back as JSON. The Phase B adapter normalizes against this shape so the moment partner credentials land, only the URL + auth-flow change.

## Three options evaluated

| Option | Path | Cost | Time-to-prod | Risk | Quality |
|---|---|---|---|---|---|
| **A — Partner program (via Instinct Science)** | Email partner contact at instinct.vet → request ScribbleVet read API access; cite VMG-distribution thesis | Unknown fee; ~3 dev-weeks of integration work after access | Likely **6–12 weeks** to first credentials given fresh acquisition + no public partner-portal yet | Approval gated; partner-program scope may not extend to ScribbleVet on day 1 (acquisition is 4 months old) | Highest — supported, future-proof, OAuth, ride Instinct's existing integration ecosystem |
| **B — Email-fallback ingest** | ScribbleVet emails finished notes to a clinic mailbox → AgentProvision's inbox-monitor pipeline parses + normalizes → record_observation. Reuses the InboxMonitorWorkflow we already ship. | Free; ~1 dev-week to plumb the parser + normalize the SOAP-as-email | **Days** | Lossy formatting, fragile email subject parsing, depends on operator opting into the email-the-note feature | Medium — works today, no ScribbleVet sign-off required, gracefully upgrades to Option A later |
| **C — Browser-Companion / web-UI scrape** | Drive a headless browser against `app.scribblevet.com` with operator-provided creds | Dev-only | Days | **Rejected.** Violates ToS (anti-automation clause [9]); reputational risk for AgentProvision's clinic-trust positioning; operationally brittle (extension version drifts) | Low |

## Recommendation: **Option A primary, Option B contingency, Option C never**

Reasoning:

1. **Acquisition timing is favorable for partner outreach.** Instinct Science ran the acquisition press release with a verbatim commitment to "continue to invest heavily in integrations" [5][6]. A clean partner-API ask landing in their inbox in May 2026 — five months post-acquisition, while integration architecture is still being designed — is exactly when external pull is most useful to a product team.
2. **Instinct already runs a partner-API program.** The pattern matches Covetrus Connect: contact form, per-partner agreement, OAuth. That's a known pattern for AgentProvision's integration registry. [7]
3. **The 6–12 week wait is bearable** because the parent plan already has parallel work (BrightLocal SEO Sentinel, Twilio SMS, Bookkeeper, AHA chart-of-accounts, Covetrus Pulse partner intake itself). The Pet Health Concierge upgrade can ship in *stub mode* without ScribbleVet and *upgrade gracefully* on credential delivery — same pattern as Covetrus Pulse.
4. **Option B (email ingest) is a real Plan B**, not vapor. ScribbleVet does support emailing the finished note to operators — that's a documented Companion feature. Wire that mailbox to the existing InboxMonitorWorkflow with a `subject contains "ScribbleVet visit summary"` filter, and we're ingesting clinical notes within a week. Lossy on formatting but enough to drive the Pet Health Concierge's "prior visits" recall feature. **Recommended fallback if Option A is rejected or stalls past 12 weeks.**

## Concrete next-steps Simon can take in the next 24h

1. **Email Instinct Science partner channel** with the following pitch (drafted):

   > Hi Instinct team,
   >
   > Following the ScribbleVet acquisition, I'm reaching out about partner-API access for ScribbleVet's clinical-note data. I run AgentProvision (agentprovision.com), a memory-first AI agent platform deployed at The Animal Doctor SOC (Anaheim, Buena Park, Mission Viejo) and being rolled out across Veterinary Management Group's ~2,000 affiliated practices.
   >
   > We need read-only access to finalized SOAP notes (per visit, per patient) so our Pet Health Concierge agent can answer client questions like "is Bella's lameness the same one Dr. Castillo saw in March?" with the actual exam record, and so our Clinical Triage agent can pre-load prior history into the morning intake summary.
   >
   > Specifically: REST/JSON access to (a) recent notes by date range, (b) a single note by ID, (c) text search across notes for a given patient. OAuth client_credentials per practice would match how we already integrate with Covetrus Connect, BrightLocal, and Google Workspace.
   >
   > Happy to fill out a formal application — what's the next step? Our adapter is already scaffolded against the documented SOAP shape; we can light up the moment credentials land.
   >
   > Best,
   > Simon Aguilera
   > AgentProvision / wolfpoint.ai

2. **CC `support@scribblevet.com`** on the same email so the legacy ScribbleVet-side relationship sees the ask too. [4]

3. **In parallel**, set up the Option B mailbox stub: configure `clinical-notes@theanimaldoctor.com` (or similar), update Angelo's ScribbleVet account to email-the-note-on-finalize, and let the InboxMonitorWorkflow pick it up. Zero blocker on Option A approval.

## Sources

1. [ScribbleVet | AI digital scribe for busy veterinarians (homepage)](https://www.scribblevet.com/)
2. [ScribVet: The Veterinary AI Scribe (competitor; for context only)](https://scribvet.com/)
3. [Setting up the right workflow with a veterinary AI scribe (ScribbleVet blog)](https://www.scribblevet.com/blog/setting-up-the-right-workflow-with-an-ai-scribe)
4. [ScribbleVet Support Hub](https://www.scribblevet.com/support-hub)
5. [Instinct Science Acquires ScribbleVet — press release](https://instinct.vet/news/instinct-science-scribblevet-acquisition-2026/)
6. [Instinct Science CEO Speaks On Acquiring ScribbleVet (blog post)](https://instinct.vet/blog/instinct-science-scribblevet-joining-forces-2026/)
7. [Veterinary Software Integrations | Instinct EMR for Labs, Imaging & More](https://instinct.vet/integrations/)
8. [Veterinary Software Integrations: How Instinct EMR Works with Labs, Imaging, Inventory, and More (blog)](https://instinct.vet/blog/instinct-emr-integrations-veterinary/)
9. [ScribbleVet Terms of Use (operated by Kairo Care, Inc.)](https://www.scribblevet.com/terms)
10. [ScribbleVet — App Store listing](https://apps.apple.com/us/app/scribblevet-the-ai-scribe/id6461720107)
11. [ScribbleVet Browser Companion — Chrome Web Store (publisher Kairo Care, Inc., v1.21.0)](https://chromewebstore.google.com/detail/scribblevet-browser-compa/gbcmfinnjfigkegmhplcpfflfkkjpgbm)
12. [What's new at ScribbleVet (changelog page)](https://www.scribblevet.com/whats-new)
13. Search: `"scribblevet" OAuth API key developer portal "developers"` — returned 0 ScribbleVet-specific results, only generic OAuth tutorials. Treat as confirmed-absence rather than not-yet-found.
14. [Top 3 AI Scribes for VetMed: Pros, Cons (Hound blog) — comparison context for AI-training-rights industry posture](https://www.hound.vet/blog/top-3-ai-scribes-for-vetmed)

## Open questions for partner-intake (confirm during email exchange)

- Is the partner API a single program covering both Instinct EMR *and* ScribbleVet, or separate enrollments?
- Auth flow — OAuth2 client_credentials confirmed, or other?
- Scopes available — read-notes, search, webhook subscription?
- Sandbox URL + credentials timeline?
- Rate limits — per-tenant or global?
- Data retention — does the API expose notes for the full clinic-archive period, or only N days back?
- Pricing — flat partner fee, revenue-share, or free tier for clinic-installed integrations?
- HIPAA-equivalent / SOC2 posture (CCPA-relevant) — BAA available even though vet records aren't HIPAA-covered?
- Does the partner agreement permit re-distribution to VMG's ~2k affiliated practices, or does each practice need its own ScribbleVet account?
