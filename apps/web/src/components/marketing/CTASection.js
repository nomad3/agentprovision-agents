import { useRef } from 'react';
import { motion, useInView, useReducedMotion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { track } from '../../services/marketingAnalytics';

/**
 * Bottom-of-page CTA card.
 *
 * Props:
 * - registerHref: absolute URL to send the CTA click to. Default
 *   (undefined) uses react-router `/register`. Alpha landing passes
 *   the apex URL so subdomain visitors land on a working auth flow.
 *   PR #450 review BLOCKER B1.
 */
export default function CTASection({ registerHref } = {}) {
  const { t } = useTranslation('landing');
  const navigate = useNavigate();
  const ref = useRef(null);
  const isInView = useInView(ref, { once: true, margin: '-80px 0px' });
  const prefersReducedMotion = useReducedMotion();

  const onClick = () => {
    track('cta_get_started_click', { location: 'footer_cta' });
    if (registerHref) {
      window.location.assign(registerHref);
    } else {
      navigate('/register');
    }
  };

  return (
    <section className="cta-v2">
      <motion.div
        ref={ref}
        className="cta-v2__inner"
        initial={prefersReducedMotion ? {} : { opacity: 0, scale: 0.98 }}
        animate={isInView ? { opacity: 1, scale: 1 } : {}}
        transition={{ duration: 0.5 }}
      >
        <h2 className="cta-v2__heading">{t('cta.heading')}</h2>
        <p className="cta-v2__sub">{t('cta.subtext')}</p>
        <motion.button
          className="cta-v2__btn"
          onClick={onClick}
          whileHover={prefersReducedMotion ? {} : { scale: 1.02 }}
          whileTap={prefersReducedMotion ? {} : { scale: 0.98 }}
          transition={{ type: 'spring', stiffness: 400, damping: 17 }}
        >
          {t('cta.button')}
        </motion.button>
      </motion.div>
    </section>
  );
}
