import { useRef } from 'react';
import { motion, useReducedMotion, useScroll, useTransform } from 'framer-motion';
import {
  FaCheckCircle,
  FaCloudUploadAlt,
  FaFolderOpen,
  FaNotesMedical,
  FaShieldAlt,
  FaUserCheck,
} from 'react-icons/fa';

const STAGES = [
  {
    icon: FaCloudUploadAlt,
    label: '01',
    title: 'Packet enters',
    body: 'Drive and OneDrive files become one case packet.',
    meta: '5 sources',
  },
  {
    icon: FaFolderOpen,
    label: '02',
    title: 'Evidence indexed',
    body: 'Owner history, symptoms, invoices, and notes stay traceable.',
    meta: 'source map',
  },
  {
    icon: FaNotesMedical,
    label: '03',
    title: 'Draft prepared',
    body: 'The right agent creates the intake, SOAP, billing, or referral draft.',
    meta: 'review ready',
  },
  {
    icon: FaShieldAlt,
    label: '04',
    title: 'Guardrails fire',
    body: 'Red flags, missing facts, and financial changes pause for approval.',
    meta: 'policy gate',
  },
  {
    icon: FaUserCheck,
    label: '05',
    title: 'Human owns it',
    body: 'Staff approve, edit, route, or send with the full audit trail intact.',
    meta: 'signed off',
  },
];

const LEDGER = [
  'owner-history.pdf',
  'triage-call.md',
  'SOAP-draft.docx',
  'invoice-review.csv',
];

export default function VetCaseFlow() {
  const ref = useRef(null);
  const prefersReducedMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start 78%', 'end 34%'],
  });
  const railScale = useTransform(scrollYProgress, [0, 1], [0.06, 1]);
  const ledgerY = useTransform(scrollYProgress, [0, 1], [20, -20]);

  return (
    <section className="vet-caseflow" ref={ref}>
      <div className="vet-caseflow__inner">
        <motion.div
          className="vet-caseflow__copy"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: '-90px' }}
          transition={{ duration: 0.55, ease: [0.16, 1, 0.3, 1] }}
        >
          <span className="vet-section-kicker vet-section-kicker--dark">Live case flow</span>
          <h2>Make the invisible work visible.</h2>
          <p>
            Every file packet becomes evidence, every draft carries provenance,
            and every risky action pauses at a named approval gate before it
            reaches the client or the medical record.
          </p>
        </motion.div>

        <div className="vet-caseflow__console" aria-label="Animated veterinary case flow">
          <div className="vet-caseflow__console-top">
            <div>
              <span className="vet-caseflow__eyebrow">Case packet</span>
              <strong>Milo · same-day triage</strong>
            </div>
            <span className="vet-caseflow__live">
              <FaCheckCircle aria-hidden="true" />
              audit trail active
            </span>
          </div>

          <div className="vet-caseflow__stage-wrap">
            <div className="vet-caseflow__rail" aria-hidden="true">
              <motion.span style={prefersReducedMotion ? undefined : { scaleX: railScale, scaleY: railScale }} />
            </div>

            {STAGES.map((stage, index) => {
              const Icon = stage.icon;
              return (
                <motion.article
                  className="vet-caseflow__stage"
                  key={stage.title}
                  initial={prefersReducedMotion ? false : { opacity: 0, y: 28, scale: 0.97 }}
                  whileInView={{ opacity: 1, y: 0, scale: 1 }}
                  viewport={{ once: true, margin: '-80px' }}
                  transition={{ duration: 0.48, delay: index * 0.08, ease: [0.16, 1, 0.3, 1] }}
                  whileHover={prefersReducedMotion ? undefined : { y: -5 }}
                >
                  <span className="vet-caseflow__stage-number">{stage.label}</span>
                  <span className="vet-caseflow__stage-icon" aria-hidden="true"><Icon /></span>
                  <h3>{stage.title}</h3>
                  <p>{stage.body}</p>
                  <span className="vet-caseflow__stage-meta">{stage.meta}</span>
                </motion.article>
              );
            })}
          </div>

          <motion.div
            className="vet-caseflow__ledger"
            style={prefersReducedMotion ? undefined : { y: ledgerY }}
            aria-label="Source packet examples"
          >
            <span className="vet-caseflow__ledger-title">Source packet</span>
            {LEDGER.map((item, index) => (
              <motion.span
                className="vet-caseflow__ledger-item"
                key={item}
                initial={prefersReducedMotion ? false : { opacity: 0, x: 16 }}
                whileInView={{ opacity: 1, x: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.38, delay: 0.22 + index * 0.08 }}
              >
                {item}
              </motion.span>
            ))}
          </motion.div>

          <span className="vet-caseflow__packet vet-caseflow__packet--one" aria-hidden="true" />
          <span className="vet-caseflow__packet vet-caseflow__packet--two" aria-hidden="true" />
          <span className="vet-caseflow__packet vet-caseflow__packet--three" aria-hidden="true" />
        </div>
      </div>
    </section>
  );
}
