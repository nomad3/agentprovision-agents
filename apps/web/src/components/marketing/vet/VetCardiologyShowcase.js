import { motion, useReducedMotion } from 'framer-motion';

const STEPS = [
  {
    num: '01',
    actor: 'Referral intake',
    title: 'Referral files land in Drive',
    body: 'The referral email, history, images, and prior notes are gathered in one place.',
  },
  {
    num: '02',
    actor: 'Diagnostics room',
    title: 'Key details are organized',
    body: 'Measurements, missing fields, prior comparisons, and questions for the specialist are placed in a review table.',
  },
  {
    num: '03',
    actor: 'Report room',
    title: 'Draft report is prepared',
    body: 'The report starts in the practice template with links back to the files Dr. Brett needs to check.',
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
          From uploaded echo files to a cardiology report ready for Dr. Brett.
        </h2>
        <p className="vet-cardio__subtitle">
          The goal is not to replace the specialist. It is to gather the case,
          reduce formatting work, and make the final review easier.
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
          Cardiology is one depth example. The same draft-then-review pattern
          can support GP triage, visit notes, billing review, inventory, and
          client follow-up.
        </p>
      </div>
    </section>
  );
}
