import { useRef } from 'react';
import { motion, useReducedMotion, useScroll, useTransform } from 'framer-motion';
import { track } from '../../../services/marketingAnalytics';

// Auth always lives on the apex — cloudflared only routes /api/* on
// agentprovision.com, so subdomain visitors register/sign-in there.
// Mirrors the APEX_REGISTER pattern from AlphaHero (PR #450 B1).
const APEX_REGISTER = 'https://agentprovision.com/register';

const HERO_STATS = [
  {
    value: 'File-first',
    label: 'Starts with your existing Drive and OneDrive files',
  },
  {
    value: 'Review-ready',
    label: 'Summaries, notes, and follow-ups prepared for staff',
  },
  {
    value: 'Connect later',
    label: 'Practice software can be added when the team is ready',
  },
];

const TRACE_ROWS = [
  { width: '72%', offset: '8%', delay: 0 },
  { width: '48%', offset: '38%', delay: 0.4 },
  { width: '82%', offset: '0%', delay: 0.8 },
  { width: '58%', offset: '24%', delay: 1.2 },
  { width: '68%', offset: '12%', delay: 1.6 },
];

export default function VetHero() {
  const sectionRef = useRef(null);
  const prefersReducedMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ['start start', 'end start'],
  });
  const textY = useTransform(scrollYProgress, [0, 1], [0, 44]);
  const statsY = useTransform(scrollYProgress, [0, 1], [0, 76]);
  const traceY = useTransform(scrollYProgress, [0, 1], [0, -34]);
  const traceOpacity = useTransform(scrollYProgress, [0, 0.72], [0.92, 0.18]);

  return (
    <section className="vet-hero" id="top" ref={sectionRef}>
      <div className="vet-hero__bg" />
      <motion.div
        className="vet-hero__clinical-trace"
        aria-hidden="true"
        style={prefersReducedMotion ? undefined : { y: traceY, opacity: traceOpacity }}
      >
        <div className="vet-hero__trace-shell">
          {TRACE_ROWS.map((row, index) => (
            <span
              className="vet-hero__trace-row"
              key={`${row.width}-${row.offset}`}
              style={{
                '--trace-width': row.width,
                '--trace-offset': row.offset,
                '--trace-delay': `${row.delay}s`,
                '--trace-index': index,
              }}
            />
          ))}
        </div>
      </motion.div>

      <div className="vet-hero__content">
        <motion.div
          className="vet-hero__text"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          style={prefersReducedMotion ? undefined : { y: textY }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        >
          <span className="vet-hero__badge">Veterinary Team Support</span>
          <span className="vet-hero__script">Calm medicine, clearer workdays.</span>
          <h1 className="vet-hero__title">
            AI support for busy veterinary teams.
          </h1>
          <p className="vet-hero__subtitle">
            One place to organize intake, records, notes, billing questions,
            and follow-ups. AI prepares the work so licensed staff can review,
            edit, and decide.
          </p>

          <ul className="vet-hero__assurances" aria-label="What stays true">
            <li className="vet-hero__assurance">Built around real practice work</li>
            <li className="vet-hero__assurance">Shows what it used</li>
            <li className="vet-hero__assurance">Connects to practice software later</li>
          </ul>

          <div className="vet-hero__ctas">
            {/* Anchors styled as buttons — a real <button> nested inside
                <a> is invalid DOM (React nesting warning). The button
                classes carry the identical visual style. Absolute apex
                href so the auth flow always resolves — cloudflared only
                routes /api/* on the apex hostname. */}
            <a
              className="vet-hero__cta-primary"
              href={APEX_REGISTER}
              onClick={() => track('vet_get_started_click', { location: 'hero' })}
            >
              Request access
            </a>
            <a
              className="vet-hero__cta-ghost"
              href="#safety"
              onClick={() => track('vet_see_safety_click', { location: 'hero' })}
            >
              See the safety model
            </a>
          </div>
        </motion.div>

        <motion.div
          className="vet-hero__stats"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          style={prefersReducedMotion ? undefined : { y: statsY }}
          transition={{ duration: 0.6, ease: 'easeOut', delay: 0.2 }}
          aria-label="MVP readiness model"
        >
          {HERO_STATS.map((item) => (
            <div className="vet-hero__stat" key={item.value}>
              <span className="vet-hero__stat-value">{item.value}</span>
              <span className="vet-hero__stat-label">{item.label}</span>
            </div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
