import { motion, useReducedMotion } from 'framer-motion';
import {
  FaBoxes,
  FaChartLine,
  FaDesktop,
  FaFileMedical,
  FaNotesMedical,
  FaReceipt,
  FaStar,
  FaStethoscope,
} from 'react-icons/fa';

const PRACTICE_FLOWS = [
  {
    icon: FaFileMedical,
    name: 'New Visit Intake',
    category: 'Owner + patient context',
    body: 'New-client forms, history, visit reason, preferred location, and attachments are pulled together for the team.',
  },
  {
    icon: FaStethoscope,
    name: 'Triage Support',
    category: 'Red flags first',
    body: 'Owner messages are sorted by urgency, with emergency signs and missing details called out clearly.',
  },
  {
    icon: FaNotesMedical,
    name: 'Visit Note Draft',
    category: 'Clinician review',
    body: 'Visit notes and transcripts become a first draft, with unclear points marked for the DVM to confirm.',
  },
  {
    icon: FaReceipt,
    name: 'Billing Review',
    category: 'Exceptions surfaced',
    body: 'Invoices, charge sheets, refunds, discounts, and missing codes are grouped for manager review.',
  },
  {
    icon: FaBoxes,
    name: 'Inventory + Pharmacy',
    category: 'Count-sheet discipline',
    body: 'Dispense logs, reorder points, expirations, and controlled-substance questions stay visible until resolved.',
  },
  {
    icon: FaStar,
    name: 'Review Replies',
    category: 'Approve before public',
    body: 'Public replies and client messages are drafted from practice facts and held for approval before posting.',
  },
  {
    icon: FaChartLine,
    name: 'Daily Practice Brief',
    category: 'Practice signal',
    body: 'Location load, open follow-ups, recall work, revenue files, and billing questions roll into one daily view.',
  },
  {
    icon: FaDesktop,
    name: 'Practice Software Prep',
    category: 'Safe path later',
    body: 'Common screens and safe fields are documented before future practice-software automation is turned on.',
  },
];

export default function VetConnectors() {
  const prefersReducedMotion = useReducedMotion();
  return (
    <section className="vet-connectors" id="mission">
      <div className="vet-connectors__inner">
        <span className="vet-section-kicker">Mission</span>
        <h2 className="vet-connectors__title">Start with the work your team already does.</h2>
        <p className="vet-connectors__subtitle">
          The first version works from the files your practice already uses in
          Google Drive and OneDrive. It organizes each case, prepares
          review-ready drafts, and keeps the final decision with your team.
        </p>

        <div className="vet-connectors__grid">
          {PRACTICE_FLOWS.map((c, i) => {
            const Icon = c.icon;
            return (
              <motion.div
                key={c.name}
                className="vet-connectors__card"
                initial={prefersReducedMotion ? false : { opacity: 0, y: 18 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-40px' }}
                transition={{ duration: 0.45, delay: i * 0.04 }}
              >
                <div className="vet-connectors__card-head">
                  <span className="vet-connectors__card-icon" aria-hidden="true"><Icon /></span>
                  <span className="vet-connectors__card-cat">{c.category}</span>
                </div>
                <h3 className="vet-connectors__card-name">{c.name}</h3>
                <p className="vet-connectors__card-body">{c.body}</p>
              </motion.div>
            );
          })}
        </div>

        <p className="vet-connectors__footnote">
          Connections to your practice software, scribe, payment, messaging,
          and inventory systems can come later. The file-first lane gives Dr.
          Angelo's GP team and Dr. Brett's specialty team useful help right
          away.
        </p>
      </div>
    </section>
  );
}
