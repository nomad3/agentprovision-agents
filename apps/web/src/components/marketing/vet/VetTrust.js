import { motion, useReducedMotion } from 'framer-motion';

const PILLARS = [
  {
    icon: '01',
    title: 'Deterministic where it matters',
    body:
      'Red flags, missing records, controlled-substance mismatches, and ' +
      'approval boundaries are handled as workflow rules. Unvalidated paths ' +
      'are surfaced for staff instead of smoothed over.',
    proof: 'routing rules · missing-source blocks · approval gates',
  },
  {
    icon: '02',
    title: 'Clinician-led by design',
    body:
      'Agents draft, triage, summarize, and prepare. They do not diagnose, ' +
      'prescribe, alter records, post payments, or send sensitive messages ' +
      'without the practice team approving the decision.',
    proof: 'licensed staff stays accountable',
  },
  {
    icon: '03',
    title: 'Fully auditable',
    body:
      'Every packet, draft, and handoff records the source file, stated ' +
      'assumptions, confidence, approver, and next action. You can reconstruct ' +
      'why a workflow moved the way it did.',
    proof: 'source · assumption · confidence · approver',
  },
  {
    icon: '04',
    title: 'Practice memory compounds',
    body:
      'Each approved case leaves behind structured operational memory: what ' +
      'worked, what was missing, who handled it, and what should be faster next ' +
      'time across the practice.',
    proof: 'case packets become reusable intelligence',
  },
];

export default function VetTrust() {
  const prefersReducedMotion = useReducedMotion();
  return (
    <section className="vet-trust" id="safety">
      <div className="vet-trust__inner">
        <span className="vet-section-kicker vet-section-kicker--dark">Trust & safety</span>
        <h2 className="vet-trust__title">Safety is the workflow, not a banner claim.</h2>
        <p className="vet-trust__subtitle">
          A veterinary agent system earns its place only when it behaves like
          accountable clinical infrastructure: bounded, cited, reviewable, and
          explicit about what it does not know.
        </p>

        <div className="vet-trust__grid">
          {PILLARS.map((p, i) => (
            <motion.div
              key={p.title}
              className="vet-trust__pillar"
              initial={prefersReducedMotion ? false : { opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-40px' }}
              transition={{ duration: 0.5, delay: i * 0.1 }}
            >
              <div className="vet-trust__pillar-icon" aria-hidden="true">{p.icon}</div>
              <h3 className="vet-trust__pillar-title">{p.title}</h3>
              <p className="vet-trust__pillar-body">{p.body}</p>
              <p className="vet-trust__pillar-proof">{p.proof}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
