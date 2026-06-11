import { motion, useReducedMotion } from 'framer-motion';

const STEPS = [
  {
    num: '01',
    actor: 'Referral intake',
    title: 'Echo packet lands in Drive',
    body: 'Referral email, patient signalment, history, images, and prior notes are assembled as one source-traceable packet.',
  },
  {
    num: '02',
    actor: 'Diagnostics room',
    title: 'Measurements are extracted',
    body: 'Key values, missing fields, prior comparison points, and uncertainty markers are pulled into a structured review table.',
  },
  {
    num: '03',
    actor: 'Report room',
    title: 'Specialist draft is prepared',
    body: 'The report is drafted in the practice template with citations back to source files and explicit fields for DVM edits.',
  },
  {
    num: '04',
    actor: 'Dr. Brett',
    title: 'Specialist signs off',
    body: 'The cardiologist reviews, edits, and approves before anything is sent back. The agent assembles; the veterinarian decides.',
    gate: true,
  },
];

export default function VetCardiologyShowcase() {
  const prefersReducedMotion = useReducedMotion();
  return (
    <section className="vet-cardio" id="example">
      <div className="vet-cardio__inner">
        <span className="vet-cardio__eyebrow">Specialist example</span>
        <h2 className="vet-cardio__title">
          From uploaded echo packet to review-ready cardiology report.
        </h2>
        <p className="vet-cardio__subtitle">
          Medical-grade trust is not just about a better answer. It is about a
          better clinical pathway: structured inputs, cited findings, named
          expert review, and a permanent case artifact after approval.
        </p>

        <ol className="vet-cardio__steps">
          {STEPS.map((s, i) => (
            <motion.li
              key={s.num}
              className={`vet-cardio__step${s.gate ? ' vet-cardio__step--gate' : ''}`}
              initial={prefersReducedMotion ? false : { opacity: 0, y: 18 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-40px' }}
              transition={{ duration: 0.45, delay: i * 0.08 }}
            >
              <span className="vet-cardio__step-num" aria-hidden="true">{s.num}</span>
              <div className="vet-cardio__step-text">
                <span className="vet-cardio__step-actor">{s.actor}</span>
                <h3 className="vet-cardio__step-title">{s.title}</h3>
                <p className="vet-cardio__step-body">{s.body}</p>
                {s.gate && (
                  <span className="vet-cardio__step-badge">
                    <span aria-hidden="true">✓</span> Licensed specialist approves
                  </span>
                )}
              </div>
            </motion.li>
          ))}
        </ol>

        <p className="vet-cardio__footnote">
          Cardiology is one depth example. The same draft-then-approve pattern
          runs across GP triage, SOAP notes, billing review, inventory, and
          reputation workflows.
        </p>
      </div>
    </section>
  );
}
