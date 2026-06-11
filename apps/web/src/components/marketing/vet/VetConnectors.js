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
    name: 'Intake Packet',
    category: 'Owner + patient context',
    body: 'New-client forms, history, reason for visit, location preference, and attachments become a staff-ready packet.',
  },
  {
    icon: FaStethoscope,
    name: 'Clinical Triage',
    category: 'Red flags first',
    body: 'Symptoms are routed as emergency, same-day, routine, refill, records, billing, or follow-up with missing facts called out.',
  },
  {
    icon: FaNotesMedical,
    name: 'SOAP Draft',
    category: 'Clinician review',
    body: 'Visit notes and transcripts turn into structured SOAP drafts with unclear source language marked for DVM confirmation.',
  },
  {
    icon: FaReceipt,
    name: 'Billing Review',
    category: 'Exceptions surfaced',
    body: 'Charge sheets, invoices, refunds, discounts, and missing codes become a human-approved review packet.',
  },
  {
    icon: FaBoxes,
    name: 'Inventory + Pharmacy',
    category: 'Count-sheet discipline',
    body: 'Dispense logs, reorder thresholds, expirations, and controlled-substance exceptions stay open until reconciled.',
  },
  {
    icon: FaStar,
    name: 'Reputation Response',
    category: 'Approve before public',
    body: 'Review replies and campaign drafts are grounded in practice facts and held for staff approval before posting.',
  },
  {
    icon: FaChartLine,
    name: 'Daily Ops Brief',
    category: 'Practice signal',
    body: 'Location load, unresolved handoffs, revenue files, recall work, and billing exceptions roll into one daily brief.',
  },
  {
    icon: FaDesktop,
    name: 'PMS Readiness',
    category: 'Computer-use safe path',
    body: 'Screen maps, safe fields, and action plans are prepared before any future PMS desktop actuation is enabled.',
  },
];

export default function VetConnectors() {
  const prefersReducedMotion = useReducedMotion();
  return (
    <section className="vet-connectors" id="mission">
      <div className="vet-connectors__inner">
        <span className="vet-section-kicker">Mission</span>
        <h2 className="vet-connectors__title">Make the practice computable before you automate it.</h2>
        <p className="vet-connectors__subtitle">
          The MVP starts with the files practices already trust: Google Drive
          and OneDrive. Each workflow converts a packet into structured,
          source-traceable work that staff can approve, hand off, and audit.
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
          PMS, scribe, payment, messaging, and inventory integrations come
          later. The file-first lane gives Dr. Angelo-style GP teams and
          Dr. Brett-style specialist workflows usable structure now.
        </p>
      </div>
    </section>
  );
}
