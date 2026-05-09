# Angelo — Platform Inventory (15-min check)

**To:** Angelo
**From:** Simon
**Date:** 2026-05-09

---

## Cover note

Angelo — to wire AgentProvision into your practice cleanly we need to know exactly which vendor sits at each layer (phone, CMS, payments, etc.). I've pre-filled the rows we already covered on our last call so you only **confirm or correct** the rest. Should take ~15 minutes; once you send it back I can dispatch one integration specialist per platform and we stop guessing.

**How to fill:** circle/bold the option that applies, or write a name in the **Other** column. "Don't know" is a valid answer — we'll figure it out from your website footer.

---

## 1. Clinical (in-clinic)

| Layer | Options | Status |
|---|---|---|
| PMS (practice mgmt) | **Covetrus Pulse** | ✅ confirmed |
| AI scribe | **ScribbleVet** | ✅ confirmed |
| Radiology AI | Antec / **Antech Imaging Services** / SignalPET / Vetology / Other: _______ — confirm ☐ | ❓ (notes show "Antec" — likely Antech Imaging) |
| In-house lab analyzers | IDEXX / Heska / Abaxis / Other: _______ | ❓ |
| Outside lab | IDEXX Reference / Antech / Other: _______ | ❓ |
| Imaging (digital x-ray, ultrasound) | IDEXX-CR / Sound / Other: _______ | ❓ |
| Anesthesia monitor | Cardell / Bionet / Other: _______ | ❓ |
| Telemedicine | TeleVet / Anipanion / Other: _______ / **none** | ❓ |

## 2. Communication

| Layer | Options | Status |
|---|---|---|
| Practice email host | **Microsoft 365** (assumed from theanimaldoctorsoc.com billing inboxes) — confirm ☐ vs Google Workspace | ❓ |
| Calendar | **Google Calendar** | ✅ confirmed |
| Clinic phone / VOIP | RingCentral / Vonage / Spectrum Business / Spruce / OpenPhone / Weave / Other: _______ | ❓ |
| Voicemail transcription | included w/ phone / Otter / Rev / Other: _______ / none | ❓ |
| Texting platform | Twilio / Weave / Spruce / Other: _______ / none | ❓ |
| Internal staff chat | Slack / Teams / Discord / Other: _______ / none | ❓ |

## 3. Website + Marketing

| Layer | Options | Status |
|---|---|---|
| SEO / local listings | **BrightLocal** | ✅ confirmed |
| Marketing agency | **Genius Events** (current — flag if being replaced ☐) | ✅ confirmed |
| Website CMS | WordPress / Squarespace / Wix / ProSites / iVET360 (formerly IDA Vet) / Other: _______ | ❓ |
| Hosting | self-hosted / WordPress.com / Bluehost / Other: _______ | ❓ |
| Domain registrar | GoDaddy / Namecheap / Google Domains / Other: _______ | ❓ |
| Google Business Profile | yes (one per location) / no | ❓ |
| Yelp | yes (claimed) / no | ❓ |
| Online review collector | BirdEye / Podium / Weave / Other: _______ / manual | ❓ |
| Paid ads running | Google Ads / Meta Ads / TikTok / **none** (circle all) | ❓ |
| Email newsletter | Mailchimp / Constant Contact / Klaviyo / Other: _______ / none | ❓ |

## 4. Pharmacy

| Layer | Options | Status |
|---|---|---|
| Home-delivery pharmacy | Covetrus Vets First Choice / Vetsource / Chewy Pharmacy / Mixlab (compounding) / Wedgewood Connect (compounding) / Other: _______ | ❓ |
| In-clinic dispensing | manual via Pulse / external: _______ | ❓ |
| Controlled-substance log | paper / e-log (Cubex / CompuMed / VetLogic / DEA-DASH) / Other: _______ | ❓ |

## 5. Finance + Billing

| Layer | Options | Status |
|---|---|---|
| Accounting | QuickBooks Desktop / QuickBooks Online / Xero / Sage Intacct / NetSuite / FreshBooks / Wave / Other: _______ | ❓ |
| CPA name + email | _________________________ | ❓ |
| Payment processor | OpenEdge (Pulse default) / CardConnect / Square / Heartland / Stripe / Other: _______ | ❓ |
| Client financing | CareCredit / Scratchpay / Sunbit / Wells Fargo Health Advantage / Other: _______ / none | ❓ |
| Pet insurance verifier | Trupanion Express / Pawlicy Advisor / Other: _______ / none | ❓ |
| Wellness plan billing | manual / SimplePractice / Other: _______ / none | ❓ |

## 6. Insurance carriers (for claim pre-fill)

Circle every carrier you see regularly:
**Trupanion** / **Nationwide** / **Pets Best** / **Healthy Paws** / **Embrace** / **Lemonade** / **Spot** / **Figo** / **ASPCA** / **MetLife Pet** / Other: _______

Estimated % of clients with pet insurance: **____%**

## 7. Operations + HR

| Layer | Options | Status |
|---|---|---|
| Staff scheduling | When I Work / Homebase / Deputy / Other: _______ / manual | ❓ |
| Payroll | Gusto / ADP / Paychex / Heartland / Other: _______ | ❓ |
| HR | Gusto / Rippling / BambooHR / Other: _______ / manual | ❓ |
| OSHA compliance log | paper / Vetter / Other: _______ | ❓ |
| CE tracking | VetGirl / VIN / Other: _______ / manual | ❓ |
| Benchmarking | **VMG** (member) | ✅ confirmed |

## 8. Compliance + IT

| Layer | Options | Status |
|---|---|---|
| State vet board | California Veterinary Medical Board (assumed) — confirm ☐ | ❓ |
| DEA license expiry tracking | manual calendar / e-log: _______ | ❓ |
| Cybersecurity / IT support managed by | in-house / MSP name: _______ | ❓ |
| Shared drive | Google Drive / Dropbox / OneDrive / Other: _______ | ❓ |
| Password manager | 1Password / LastPass / Other: _______ / none | ❓ |
| BI / dashboard | Vetsuccess / VetCove / Looker / Other: _______ / none | ❓ |

---

## Next steps once you send this back

> **Within 48 hours of receiving this, we dispatch integration specialists for:**
>
> 1. **Phone / VOIP** → call-recording → Pulse note auto-attach
> 2. **Accounting + payment processor** → daily reconciliation into your CPA's inbox
> 3. **Pet-insurance carriers** (top 2 you circle) → one-click claim pre-fill from the patient record
> 4. **Website CMS + review collector** → owner-facing Pet Health Concierge embeds in the right place
> 5. **Controlled-substance log** → DEA-compliant digital trail (replaces paper if applicable)
>
> Each one is a 1–2 day build per platform once we know the vendor. Today we're guessing; after this form we're shipping.

Reply with this filled in, photo of a printout, or just paste your answers in an email — whatever's fastest.

— Simon
