import { useRef } from 'react';
import { motion, useReducedMotion, useScroll, useTransform } from 'framer-motion';
import { FaCheckCircle, FaFolderOpen, FaUserMd } from 'react-icons/fa';
import dogExam from '../../../assets/marketing/vet/patient-dog-exam.png';
import catConsult from '../../../assets/marketing/vet/patient-cat-consult.png';
import cardioDog from '../../../assets/marketing/vet/patient-cardio-dog.png';

const JOURNEYS = [
  {
    image: dogExam,
    label: 'GP visit',
    title: 'Dog visit summary',
    body: 'History, visit reason, phone notes, and follow-up tasks stay tied to the patient.',
    status: 'Intake ready',
  },
  {
    image: catConsult,
    label: 'Feline care',
    title: 'Cat consult prep',
    body: 'Owner concerns, missing records, and questions for the clinician are separated before the visit starts.',
    status: 'Visit needs sorted',
  },
  {
    image: cardioDog,
    label: 'Specialty lane',
    title: 'Cardiology review',
    body: 'Echo files and prior history are gathered into a specialist draft that Dr. Brett can review.',
    status: 'Vet review ready',
  },
];

export default function VetPatientJourneys() {
  const sectionRef = useRef(null);
  const prefersReducedMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: sectionRef,
    offset: ['start end', 'end start'],
  });
  const beltX = useTransform(scrollYProgress, [0, 1], ['-18%', '18%']);

  return (
    <section className="vet-patients" id="patients" ref={sectionRef}>
      <div className="vet-patients__inner">
        <div className="vet-patients__header">
          <span className="vet-section-kicker">Patients</span>
          <h2 className="vet-patients__title">Start with the patient, then organize the work around them.</h2>
          <p className="vet-patients__subtitle">
            Every view should feel grounded in a real appointment: why the pet
            is here, what the owner said, what is missing, and what your team
            needs to review next.
          </p>
        </div>

        <motion.div
          className="vet-patients__belt"
          aria-hidden="true"
          style={prefersReducedMotion ? undefined : { x: beltX }}
        >
          <span />
          <span />
          <span />
          <span />
        </motion.div>

        <div className="vet-patients__grid">
          {JOURNEYS.map((journey, index) => (
            <motion.article
              className="vet-patients__card"
              key={journey.title}
              initial={prefersReducedMotion ? false : { opacity: 0, y: 34 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-90px' }}
              transition={{ duration: 0.58, delay: index * 0.1, ease: [0.16, 1, 0.3, 1] }}
              whileHover={prefersReducedMotion ? undefined : { y: -6 }}
            >
              <div className="vet-patients__image-wrap">
                <motion.img
                  src={journey.image}
                  alt=""
                  className="vet-patients__image"
                  loading="lazy"
                  whileHover={prefersReducedMotion ? undefined : { scale: 1.045 }}
                  transition={{ duration: 0.55, ease: 'easeOut' }}
                />
                <span className="vet-patients__scan" aria-hidden="true" />
                <div className="vet-patients__overlay">
                  <span className="vet-patients__label">{journey.label}</span>
                  <span className="vet-patients__status">
                    <FaCheckCircle aria-hidden="true" />
                    {journey.status}
                  </span>
                </div>
              </div>

              <div className="vet-patients__copy">
                <div className="vet-patients__copy-icon" aria-hidden="true">
                  {index === 2 ? <FaUserMd /> : <FaFolderOpen />}
                </div>
                <div>
                  <h3>{journey.title}</h3>
                  <p>{journey.body}</p>
                </div>
              </div>
            </motion.article>
          ))}
        </div>
      </div>
    </section>
  );
}
