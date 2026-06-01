/**
 * Hero section for alpha.agentprovision.com.
 *
 * Different shape from the main landing's scroll-scrub video hero:
 * terminal-themed, with the install one-liner as a copyable command.
 *
 * Narrative (2026-05-31 redesign): alpha is the kernel of a NETWORK of
 * AI agents that runs whole operations — not a chatbot, not a GenAI
 * wrapper. The differentiator is a coordination substrate (memory +
 * emotions + teamwork, orchestrated) — the same loops a human
 * organization took millennia to evolve, now built into software. The
 * terminal binary is one viewport onto that substrate.
 */
import { useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { track } from '../../../services/marketingAnalytics';

const INSTALL_CMD = 'curl -fsSL https://agentprovision.com/install.sh | sh';
// Apex auth URL — see comment on AlphaLandingPage.js. PR #450 BLOCKER B1.
const APEX_REGISTER = 'https://agentprovision.com/register';

export default function AlphaHero() {
  const prefersReducedMotion = useReducedMotion();
  const [copied, setCopied] = useState(false);

  const onCopy = () => {
    navigator.clipboard.writeText(INSTALL_CMD)
      .then(() => {
        setCopied(true);
        track('alpha_install_copy', { location: 'hero' });
        setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {
        // Clipboard API can throw on non-secure contexts / older Safari.
        // PR #450 review NIT N2: surface a fallback hint rather than
        // silently swallowing. Track the failure so we can monitor it.
        track('alpha_install_copy_failed', { location: 'hero' });
      });
  };

  return (
    <section className="alpha-hero">
      <div className="alpha-hero__bg" />

      <div className="alpha-hero__content">
        <motion.div
          className="alpha-hero__text"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        >
          <span className="alpha-hero__badge">$ alpha — the agent network kernel</span>
          <h1 className="alpha-hero__title">
            A network of AI agents<br />that runs your operations.
          </h1>
          <p className="alpha-hero__subtitle">
            Not a chatbot. Not a GenAI wrapper. AgentProvision gives a fleet of agents
            a <strong>coordination substrate</strong> — durable memory, a real internal
            mood, and team structure — orchestrated from one terminal binary across
            Claude Code, Codex, Gemini CLI, and Copilot.
            <br />
            <strong>The substrate human organizations took millennia to evolve,</strong>{' '}
            now built into software.
          </p>

          <div className="alpha-hero__install">
            <code className="alpha-hero__install-cmd">{INSTALL_CMD}</code>
            <button
              type="button"
              onClick={onCopy}
              className="alpha-hero__install-copy"
              aria-label="Copy install command"
            >
              {copied ? '✓ copied' : 'copy'}
            </button>
          </div>

          <div className="alpha-hero__ctas">
            {/* Absolute href to the apex so the auth flow always
                resolves — cloudflared only routes /api/* on the apex
                hostname. PR #450 review BLOCKER B1. */}
            <a
              href={APEX_REGISTER}
              onClick={() => track('alpha_get_started_click', { location: 'hero' })}
            >
              <button className="alpha-hero__cta-primary">Get started free</button>
            </a>
            <a
              href="https://github.com/nomad3/agentprovision-agents/tree/main/apps/agentprovision-cli"
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => track('alpha_github_click', { location: 'hero' })}
            >
              <button className="alpha-hero__cta-ghost">View on GitHub →</button>
            </a>
          </div>
        </motion.div>

        <motion.div
          className="alpha-hero__terminal"
          initial={prefersReducedMotion ? false : { opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.6, ease: 'easeOut', delay: 0.2 }}
          aria-hidden="true"
        >
          <div className="alpha-hero__terminal-bar">
            <span className="alpha-hero__terminal-dot alpha-hero__terminal-dot--red" />
            <span className="alpha-hero__terminal-dot alpha-hero__terminal-dot--yellow" />
            <span className="alpha-hero__terminal-dot alpha-hero__terminal-dot--green" />
            <span className="alpha-hero__terminal-title">~ alpha coalition run --pattern incident_investigation</span>
          </div>
          <pre className="alpha-hero__terminal-body">
{`[alpha] recalled 14 prior observations from tenant memory
[alpha] spun up coalition c_91b — shared blackboard:
       • analyst   (claude)   mood: alert ▲  — careful mode
       • researcher (gemini)   trust: 0.82
       • supervisor (luna)     reading the room…
[alpha] phase gather_facts → hypothesize → prescribe
[alpha] ⏸  human approval gate: apply remediation? [y/N]

> luna: arousal high across the team — staying precise.
> recorded 6 observations · 1 commitment to memory
[alpha] c_91b COMPLETE — audit trail written`}
          </pre>
        </motion.div>
      </div>
    </section>
  );
}
