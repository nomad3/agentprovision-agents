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
    title: 'Files arrive',
    body: 'Upload records, forms, invoices, and notes from Drive or OneDrive.',
    meta: 'files together',
  },
  {
    icon: FaFolderOpen,
    label: '02',
    title: 'Story is organized',
    body: 'History, symptoms, visit reason, and billing context sit in one view.',
    meta: 'clear context',
  },
  {
    icon: FaNotesMedical,
    label: '03',
    title: 'Draft prepared',
    body: 'The right room prepares the intake, note, invoice check, or referral draft.',
    meta: 'review ready',
  },
  {
    icon: FaShieldAlt,
    label: '04',
    title: 'Safety check',
    body: 'Urgent signs, missing facts, and money changes are called out first.',
    meta: 'review needed',
  },
  {
    icon: FaUserCheck,
    label: '05',
    title: 'Team signs off',
    body: 'Your staff edit, approve, send, or save the final version.',
    meta: 'team approved',
  },
];

const LEDGER = [
  'owner-history.pdf',
  'phone-note.md',
  'visit-note-draft.docx',
  'invoice-check.csv',
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
          <span className="vet-section-kicker vet-section-kicker--dark">Daily case flow</span>
          <h2>See what needs attention next.</h2>
          <p>
            From the first form to the final follow-up, the page keeps the
            patient story, open questions, and next staff action in view before
            anything reaches an owner or medical record.
          </p>
        </motion.div>

        <div className="vet-caseflow__console" aria-label="Animated veterinary case flow">
          <div className="vet-caseflow__console-top">
            <div>
              <span className="vet-caseflow__eyebrow">Patient case</span>
              <strong>Milo · same-day visit</strong>
            </div>
            <span className="vet-caseflow__live">
              <FaCheckCircle aria-hidden="true" />
              ready for staff review
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
            aria-label="Patient case file examples"
          >
            <span className="vet-caseflow__ledger-title">Files in the case</span>
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
