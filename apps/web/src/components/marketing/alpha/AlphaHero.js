/**
 * Hero section for alpha.agentprovision.com.
 *
 * Different shape from the main landing's scroll-scrub video hero:
 * terminal-themed, with the install one-liner as a copyable command.
 * Marketing pitch: "the orchestrator CLI for AI agents" — frames alpha
 * as `kubectl for agents`, not "yet another coding CLI".
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
          <span className="alpha-hero__badge">$ alpha</span>
          <h1 className="alpha-hero__title">
            The orchestrator CLI<br />for AI agents.
          </h1>
          <p className="alpha-hero__subtitle">
            One terminal binary that orchestrates Claude Code, Codex, Gemini CLI,
            Copilot, and OpenCode — across machines, providers, and time.
            <br />
            <strong>kubectl for agents,</strong> not yet another coding CLI.
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
            <span className="alpha-hero__terminal-title">~ alpha run --fanout claude,codex,gemini</span>
          </div>
          <pre className="alpha-hero__terminal-body">
{`[alpha] dispatched fanout task t_a4f3 with 3 children:
       • t_a4f3a (claude)
       • t_a4f3b (codex)
       • t_a4f3c (gemini)
[alpha] estimated 8m, $0.42 via Claude Sonnet
[alpha] close this terminal any time —
       resume with: alpha watch t_a4f3

> opened PR #432: refactor(auth): adopt Depends pattern
> consensus: all three reviewers converged on...
[alpha] t_a4f3 COMPLETE — 7 findings, 2 blockers`}
          </pre>
        </motion.div>
      </div>
    </section>
  );
}
