import { motion, useReducedMotion } from 'framer-motion';

const PILLARS = [
  {
    icon: '01',
    title: 'Rules for high-risk moments',
    body:
      'Urgent symptoms, missing records, medication concerns, and billing ' +
      'changes are called out for staff instead of being hidden in a draft.',
    proof: 'urgent flags · missing-info checks · staff approval',
  },
  {
    icon: '02',
    title: 'Clinician-led by design',
    body:
      'The system can draft, sort, summarize, and prepare. It does not ' +
      'diagnose, prescribe, change records, post payments, or send sensitive ' +
      'messages without the practice team approving the decision.',
    proof: 'licensed staff stays accountable',
  },
  {
    icon: '03',
    title: 'Easy to review',
    body:
      'Every draft shows the files and notes it used, what it assumed, who ' +
      'approved it, and what happens next.',
    proof: 'files used · assumptions · approver',
  },
  {
    icon: '04',
    title: 'Practice memory gets better',
    body:
      'Approved cases leave a simple record of what worked, what was missing, ' +
      'who handled it, and what should be faster next time.',
    proof: 'less rework on repeat cases',
  },
];

export default function VetTrust() {
  const prefersReducedMotion = useReducedMotion();
  return (
    <section className="vet-trust" id="safety">
      <div className="vet-trust__inner">
        <span className="vet-section-kicker vet-section-kicker--dark">Trust & safety</span>
        <h2 className="vet-trust__title">Trust comes from reviewable work.</h2>
        <p className="vet-trust__subtitle">
          Veterinary teams should be able to see what the system used, what it
          is unsure about, and where a person must decide. That is the safety
          model.
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
