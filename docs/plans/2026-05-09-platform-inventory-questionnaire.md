# Plan — Angelo's Platform Inventory Questionnaire

**Owner:** Simon (sends to Angelo); sub-agent drafts the questionnaire
**Why:** The integration roadmap depends on knowing exactly which vendors Angelo uses for each platform layer. Today we know the high-level stack (Pulse, ScribbleVet, BrightLocal, etc.) from the discovery call, but several layers are unknown: phone system, CMS, ad platforms actually running, insurance carriers, financing partners, controlled-substance log mechanism. We can't research integrations for vendors we haven't named.

## Goal

Ship a one-page questionnaire Simon emails Angelo. Angelo fills it in 15 minutes. We come out the other side with a complete platform map and can dispatch integration-specialist sub-agents per platform.

## Deliverables

1. **The questionnaire itself** — `docs/onboarding/2026-05-09-angelo-platform-inventory.md` — a clean form with fields grouped by lifecycle layer (Marketing, Comms, Clinical, Finance, Compliance), each field listing the most likely vendor options as multiple-choice + a "Other / write-in" row.
2. **A Loom-ready Simon-side script** — what Simon says when he sends it (~3 sentences explaining why this unblocks the next 4 weeks of work).
3. **Auto-populated baseline** based on the discovery doc — pre-fill the answers we already know (Pulse, ScribbleVet, BrightLocal, Genius Events) so Angelo only confirms / corrects rather than starting from zero.
4. **Onboarding integration plan** — once Angelo returns the questionnaire, this becomes the input to dispatching the next round of integration sub-agents (one per platform he names).

## Scope — IN

The questionnaire covers every layer where we don't yet know the vendor:

### Communication
- [ ] Clinic phone / VOIP — RingCentral / Vonage / Spectrum Business / Spruce / OpenPhone / Weave / **other**
- [ ] Voicemail transcription — included in phone vendor / Otter / Rev / **other** / **none**
- [ ] Texting platform — Twilio / Weave / Spruce / **other** / **none**
- [ ] Practice email host — Microsoft 365 / Google Workspace / **other**

### Website + Marketing
- [ ] Website CMS — WordPress / Squarespace / Wix / ProSites / IDA Vet / **other**
- [ ] Hosting — Self-hosted / WordPress.com / Bluehost / **other**
- [ ] Domain registrar — GoDaddy / Namecheap / Google Domains / **other**
- [ ] GBP (Google Business Profile) — yes (one per location) / no
- [ ] Yelp — yes (claimed?) / no
- [ ] Online review collector — BirdEye / Podium / Weave / **other** / **manual**
- [ ] Marketing agency — Genius Events (current) / **other** — being-replaced flag
- [ ] Paid ads — Google Ads / Meta Ads / TikTok / **none**
- [ ] Email newsletter — Mailchimp / Constant Contact / Klaviyo / **other** / **none**

### Clinical (in-clinic)
- [ ] PMS — Covetrus Pulse (confirmed)
- [ ] AI scribe — ScribbleVet (confirmed)
- [ ] Radiology AI — Antec (confirmed)
- [ ] In-house lab analyzers — IDEXX / Heska / Abaxis / **other** — feed results into Pulse?
- [ ] Outside lab — IDEXX Reference Labs / Antech / **other**
- [ ] Imaging (digital x-ray, ultrasound) — IDEXX-CR / Sound / **other**
- [ ] Anesthesia monitor — Cardell / Bionet / **other**
- [ ] Telemedicine — TeleVet / Anipanion / **other** / **none**

### Pharmacy
- [ ] Home-delivery pharmacy — Covetrus Vets First Choice / Vetsource / Chewy Pharmacy / **other**
- [ ] In-clinic dispensing — manual via Pulse / external
- [ ] Controlled-substance log — paper / e-log (RxLog / DAW) / **other**

### Finance + Billing
- [ ] Accounting software — QuickBooks Desktop / QuickBooks Online / Xero / Sage Intacct / FreshBooks / Wave / **other**
- [ ] CPA name + email (so Bookkeeper exports can be cc'd directly)
- [ ] Payment processor — CardConnect / Square / Heartland / Stripe / **other**
- [ ] Client financing — CareCredit / Scratchpay / Wells Fargo Health Advantage / **other** / **none**
- [ ] Pet insurance verifier — Trupanion Express / Pawlicy Advisor / **other** / **none**
- [ ] Wellness plan billing — manual / SimplePractice / **other** / **none**

### Operations
- [ ] Staff scheduling — When I Work / Homebase / Deputy / **other** / **manual**
- [ ] Payroll — Gusto / ADP / Paychex / Heartland / **other**
- [ ] HR — Gusto / Rippling / BambooHR / **other** / **manual**
- [ ] OSHA compliance log — paper / Vetter / **other**
- [ ] CE tracking — VetGirl / VIN / **other** / **manual**

### Insurance carriers (for claim pre-fill)
- [ ] Trupanion / Nationwide / Pets Best / Healthy Paws / Embrace / Lemonade / **other**
- [ ] Estimated % of clients with insurance? (rough, to size the workflow's value)

### Compliance + Legal
- [ ] State vet board portal — California Veterinary Medical Board (likely)
- [ ] DEA license expiration calendar — manual / e-log
- [ ] Cybersecurity / HIPAA-equivalent — managed by whom?

### Internal IT
- [ ] Slack / Teams / Discord — internal staff comms
- [ ] Practice intranet / shared drive — Google Drive / Dropbox / OneDrive / **other**
- [ ] Password manager — 1Password / LastPass / **other** / **none**

### Data / Analytics
- [ ] BI dashboard — Vetsuccess / VetCove / Looker / **other** / **none**
- [ ] Benchmarking — VMG benchmarking already (yes, member)

## Scope — OUT

- Asking Angelo to *evaluate* each vendor — just naming what he uses
- Authentication / API access details — those come per-platform once we know vendor
- HIPAA / SOC 2 deep-dive

## Steps

1. Sub-agent drafts the questionnaire as a Markdown form with multi-choice rows
2. Pre-fills the layers we already know from the discovery doc (Pulse, ScribbleVet, Antec, BrightLocal, Genius Events, VMG membership)
3. Writes the Simon-side cover note (~3 sentences explaining the why)
4. Output committed under `docs/onboarding/2026-05-09-angelo-platform-inventory.md`
5. Simon emails Angelo (or sends via the Pet Health Concierge once that's live for owner-facing use)

## Definition of Done

- ✅ Questionnaire markdown committed under `docs/onboarding/`
- ✅ Pre-filled rows for layers we already know
- ✅ Simon-side cover-note paragraph included
- ✅ "Once you return this, we dispatch integrations for X, Y, Z" callout that frames the urgency without being pushy
- ✅ PR on `docs/angelo-platform-inventory`, assigned to nomad3, no AI credit lines
- ✅ ≤2 pages when printed (this is a 15-minute task for Angelo, not a 1-hour audit)

## Risks

- Angelo doesn't return it — lower-effort fallback: Simon walks through it on the next call, takes notes
- He says "I don't know" for some layers (CMS, controlled-sub log) — that's a useful signal too; means we ID-research the vendor on his behalf via website footer crawling, etc.

## Cross-references

- Discovery doc (PR-prior): `docs/plans/2026-05-08-veterinary-vertical-angelo-discovery.md`
- Lifecycle audit (this conversation): the gap between what AgentProvision covers today (~25%) and the full vet practice lifecycle
