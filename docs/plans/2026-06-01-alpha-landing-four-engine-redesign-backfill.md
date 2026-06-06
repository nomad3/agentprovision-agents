# Alpha landing — four-engine substrate redesign + vet practice-OS landing (backfill)

**Date:** 2026-06-01 · **Status:** Backfilled (shipped)
**PRs:** #751 (alpha four-engine redesign), #739 (vet practice-OS landing), #752 (missing `reality` i18n label)
**Files:** `apps/web/src/AlphaLandingPage.js`, `apps/web/src/components/marketing/alpha/{AlphaEngines,AlphaMetrics,AlphaRealityLedger,AgentNetworkGraph,AlphaHero,AlphaDifferentiators,AlphaCommands,AlphaPlatformPower}.js`, `apps/web/src/AlphaLandingPage.css`, `apps/web/src/VetLandingPage.{js,css}`, `apps/web/src/components/marketing/vet/{VetHero,VetConnectors,VetAgentFleet,VetTrust,VetCardiologyShowcase}.js`, `apps/web/src/components/marketing/CTASection.js` (made prop-driven), `apps/web/src/App.js` (hostname-sniff), `apps/web/src/i18n/locales/{en,es}/landing.json`, `cloudflared/config.yml`, `kubernetes/cloudflared-deployment.yaml`

## Problem / context

The `alpha.agentprovision.com` landing led with a "kubectl for agents" / CLI-features thesis (durable tasks, fanout, recall). That undersold what the platform actually is and read as a tool, not a category. It also carried the template "AI-generated tell" — uniform `opacity:0,y:16` fade-up-on-scroll with `i*0.08` stagger on every card. Separately, the veterinary vertical (Simon + James) needed its own buyer-grade landing rather than bending the apex page. Both needed honesty guardrails so ambition wasn't mis-sold as shipped.

## What shipped

**Alpha — the four-engine substrate (#751).** The spine became the network-of-agents thesis: AgentProvision is a coordination substrate — **memory + emotions + teamwork, orchestrated** — presented as one fused system, "the merge is the moat." `AlphaLandingPage.js` now composes the section arc: `AlphaHero → AlphaEngines → AlphaMetrics → AlphaDifferentiators → AlphaRealityLedger → AlphaCommands → AlphaPlatformPower`, with nav/footer anchors `['engines','differentiators','reality','commands','platform']` (`engines` leads).

- **`AlphaEngines.js` (new, centerpiece)** — the four engines as ONE system: Memory (knowledge graph + 768-dim pgvector recall), Emotions (server-internal PAD affect model), Teamwork (A2A coalitions on a shared blackboard), Orchestration (Alpha CLI / CLI fleet / Temporal / 90+ MCP tools). The Emotions card carries the verbatim **Now / Next / Later** rollout with "Later" tagged `(roadmap)` — the honesty guardrail so no roadmap feature reads as live.
- **`AlphaMetrics.js` (new)** — grounded numbers only (4 engines, 4 CLI runtimes, 90+ MCP tools, 5.5s chat p50), reusing the `useCountUp` hook. No invented stats or logos.
- **Launch-polish squashed into the same PR** (after Codex + Luna pre-launch review converged): `AgentNetworkGraph.js` — a bespoke SVG node graph (native `<animateMotion>` SMIL, Safari-safe, GPU-light, reduced-motion static) where a single pulse flows the real pipeline `command → alpha → memory(recall) → specialists → human approval gate`, replacing the fade-up tell; and `AlphaRealityLedger.js` — honest **Live now / In alpha · guarded / Research · next** columns, doubling as objection-handling (approval, audit, isolation, BYO subscriptions). Factual fixes from Codex's review landed too (Qwen2.5-Coder → Gemma 4; softened "millennia"/"months in production"; fleet-wide emotion moved to Next, not Live).
- Refreshed copy on `AlphaHero`, `AlphaDifferentiators`, `AlphaCommands`, `AlphaPlatformPower` to tie into the substrate + human-in-the-loop guardrail; locked table rows / command set / install cmd / apex auth CTAs left unchanged (covered by `marketing/alpha` tests). i18n labels added to `en` + `es`.

**Vet — practice-OS landing (#739).** `VetLandingPage.js` mirrors the alpha setup: reuses `LandingNav`/`CTASection`/`LandingFooter` (CTASection made prop-driven, backward-compatible) and adds five vet sections — `VetHero`, `VetConnectors`, `VetAgentFleet`, `VetTrust`, `VetCardiologyShowcase` (Ocean `--land-*` tokens, `vet-` prefixed). Positioning is Luna-led: "the operating system for veterinary practices" — no clinical-autonomy claims, a licensed human approves every clinical/financial decision, cardiology is the last section as a depth example, not the headline. `App.js` extends the root hostname-sniff: `alpha.*` → AlphaLandingPage, `vet.*` → VetLandingPage, else LandingPage; `/alpha` and `/vet` also route directly. Cloudflare `vet.agentprovision.com → http://web:80` added to both `cloudflared/config.yml` and `kubernetes/cloudflared-deployment.yaml` (and the drifted `alpha` rule synced into the k8s ConfigMap to honor no-infra-drift).

**i18n fix (#752).** Live Chrome validation of the deployed #751 page showed the nav rendering the raw key `nav.reality` — the Reality Ledger anchor shipped without its label. Added `nav.reality` + `footer.links.reality` to `en` ("The ledger") and `es` ("El registro").

## Outcome

Alpha landing relaunched on the four-engine substrate narrative with a bespoke signature animation and a published Live/In-alpha/Research ledger; vet vertical got its own honesty-guarded practice-OS landing at `vet.agentprovision.com` on the same SPA bundle + tunnel. #751 reported 5 alpha suites / 15 tests (later 19 marketing tests incl. the new RealityLedger suite) green and a clean CRA build; #739 compiled clean; #752 closed the raw-key regression. Infra (cloudflared) kept in sync across config.yml + k8s ConfigMap.

## Related

- [`docs/plans/2026-05-31-landing-launch-polish.md`](2026-05-31-landing-launch-polish.md) — the Codex + Luna converged review that drove the AgentNetworkGraph + Reality Ledger + factual-fix polish folded into #751
- [`docs/marketing/empathic-teammate-vision.md`](../marketing/empathic-teammate-vision.md) — north-star (stateful/empathic/team/honest) that reframed the engines spine
- [`docs/plans/2026-05-30-agentic-vet-os-vision.md`](2026-05-30-agentic-vet-os-vision.md), [`docs/plans/2026-05-30-veterinary-mvp-discovery.md`](2026-05-30-veterinary-mvp-discovery.md) — vet-OS vision/discovery behind #739
- Memory: `vet_os_initiative.md` (agentic OS for vet practices; Luna lead), `landing_page_redesign` lineage (PR #146/#149 main-landing redesign this mirrors)
