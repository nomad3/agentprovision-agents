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
    title: 'Luna Practice Lead',
    body: 'Sends new work to the right room, keeps the case context together, and brings important decisions back to staff.',
    gate: 'Team stays in charge',
  },
  {
    icon: FaComments,
    title: 'Pet Health Concierge',
    body: 'Collects owner details, asks for missing information, and flags urgent concerns without diagnosing or prescribing.',
    gate: 'Urgent cases route to staff',
  },
  {
    icon: FaCalendarCheck,
    title: 'Front Desk Assistant',
    body: 'Prepares appointment requests, confirmations, reschedules, and new-client details for each location.',
    gate: 'Staff confirms every slot',
  },
  {
    icon: FaClipboardCheck,
    title: 'Triage Assistant',
    body: 'Sorts messages by urgency and prepares a short summary from the records and notes provided.',
    gate: 'No diagnosis, conservative routing',
  },
  {
    icon: FaNotesMedical,
    title: 'Visit Note Assistant',
    body: 'Turns transcripts, notes, and visit context into a draft note with uncertain points marked clearly.',
    gate: 'DVM approves every note',
  },
  {
    icon: FaFileInvoiceDollar,
    title: 'Billing Assistant',
    body: 'Reviews invoices, charge sheets, write-offs, refunds, and missing codes before export.',
    gate: 'Manager reviews changes',
  },
  {
    icon: FaPills,
    title: 'Inventory & Pharmacy Assistant',
    body: 'Keeps count sheets, dispense events, expirations, reorder points, and medication questions visible.',
    gate: 'Discrepancies stay open',
  },
  {
    icon: FaStarHalfAlt,
    title: 'Review Reply Assistant',
    body: 'Drafts public replies and campaign ideas from practice facts without publishing on its own.',
    gate: 'Approval before public response',
  },
  {
    icon: FaChartPie,
    title: 'Practice Operations Assistant',
    body: 'Builds a daily brief across locations, open follow-ups, revenue files, recalls, and billing questions.',
    gate: 'Flags what needs a person',
  },
  {
    icon: FaDesktop,
    title: 'Practice Software Prep Assistant',
    body: 'Documents common screens and steps so later software automation can be reviewed before it is turned on.',
    gate: 'Prep only until approved',
  },
];

export default function VetAgentFleet() {
  const prefersReducedMotion = useReducedMotion();
  return (
    <section className="vet-fleet" id="rooms">
      <div className="vet-fleet__inner">
        <span className="vet-section-kicker">Practice rooms</span>
        <h2 className="vet-fleet__title">A helper for each part of the practice day.</h2>
        <p className="vet-fleet__subtitle">
          Each room has one job and hands work back to the right person. It can
          draft, summarize, organize, and flag concerns, but your team stays in
          charge of medical and financial decisions.
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
