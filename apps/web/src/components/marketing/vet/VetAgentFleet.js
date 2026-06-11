import { motion, useReducedMotion } from 'framer-motion';
import {
  FaCalendarCheck,
  FaChartPie,
  FaClipboardCheck,
  FaComments,
  FaDesktop,
  FaFileInvoiceDollar,
  FaLock,
  FaNotesMedical,
  FaPills,
  FaStarHalfAlt,
  FaUserMd,
} from 'react-icons/fa';

const AGENTS = [
  {
    icon: FaUserMd,
    title: 'Luna Supervisor',
    body: 'Routes work across the fleet, maintains context, and keeps clinical, financial, and PMS actions inside approval boundaries.',
    gate: 'Supervisor coordinates, staff decides',
  },
  {
    icon: FaComments,
    title: 'Pet Health Concierge',
    body: 'Answers owner intake, gathers missing facts, and escalates red flags without diagnosing or prescribing.',
    gate: 'Urgent cases route to staff',
  },
  {
    icon: FaCalendarCheck,
    title: 'Front Desk Agent',
    body: 'Prepares scheduling packets, confirmations, reschedule requests, and new-client onboarding for each location.',
    gate: 'Staff confirms every slot',
  },
  {
    icon: FaClipboardCheck,
    title: 'Clinical Triage Agent',
    body: 'Classifies messages by urgency and produces one-screen summaries grounded in uploaded records.',
    gate: 'No diagnosis, conservative routing',
  },
  {
    icon: FaNotesMedical,
    title: 'SOAP Note Agent',
    body: 'Turns transcripts, notes, and visit context into structured drafts with uncertain source language marked clearly.',
    gate: 'DVM approves every note',
  },
  {
    icon: FaFileInvoiceDollar,
    title: 'Billing Agent',
    body: 'Reviews invoices, charge sheets, write-offs, refunds, and missing codes before accountant export.',
    gate: 'Manager approves exceptions',
  },
  {
    icon: FaPills,
    title: 'Inventory & Pharma Agent',
    body: 'Keeps count sheets, dispense events, expirations, reorder thresholds, and controlled-substance issues visible.',
    gate: 'Discrepancies stay open',
  },
  {
    icon: FaStarHalfAlt,
    title: 'Reputation & Growth Agent',
    body: 'Drafts review replies and campaign ideas from measured practice signals without publishing autonomously.',
    gate: 'Approval before public response',
  },
  {
    icon: FaChartPie,
    title: 'Practice Operations Agent',
    body: 'Builds daily operator briefs across locations, unresolved handoffs, revenue packets, recall backlog, and readiness.',
    gate: 'Separates file-backed facts from future fields',
  },
  {
    icon: FaDesktop,
    title: 'PMS Operator Agent',
    body: 'Maps PMS screens, identifies safe fields, and prepares human-approved desktop action plans for the computer-use lane.',
    gate: 'Readiness-only until enabled',
  },
];

export default function VetAgentFleet() {
  const prefersReducedMotion = useReducedMotion();
  return (
    <section className="vet-fleet" id="rooms">
      <div className="vet-fleet__inner">
        <span className="vet-section-kicker">Practice rooms</span>
        <h2 className="vet-fleet__title">A named agent room for every core workflow.</h2>
        <p className="vet-fleet__subtitle">
          This is clinical infrastructure, not a generic chatbot. Each room has
          a defined job, a bounded source of truth, and an explicit handoff to
          the human who owns the decision.
        </p>

        <div className="vet-fleet__grid">
          {AGENTS.map((a, i) => {
            const Icon = a.icon;
            return (
              <motion.div
                key={a.title}
                className="vet-fleet__card"
                initial={prefersReducedMotion ? false : { opacity: 0, y: 18 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: '-40px' }}
                transition={{ duration: 0.45, delay: i * 0.04 }}
              >
                <div className="vet-fleet__card-icon" aria-hidden="true"><Icon /></div>
                <h3 className="vet-fleet__card-title">{a.title}</h3>
                <p className="vet-fleet__card-body">{a.body}</p>
                <p className="vet-fleet__card-gate">
                  <span className="vet-fleet__card-gate-icon" aria-hidden="true"><FaLock /></span>
                  {a.gate}
                </p>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
