import { useEffect, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { track } from '../../services/marketingAnalytics';

// Default link set for the main agentprovision.com landing. Alpha
// landing passes its own (differentiators / commands / platform) via
// the `links` prop so the reused nav doesn't render dead anchors.
// PR #450 review IMPORTANT I1.
const DEFAULT_LINKS = ['platform', 'features', 'integrations', 'pricing'];

/**
 * Shared landing-page navigation bar.
 *
 * Props (all optional, default to main-landing behaviour):
 * - links: array of anchor keys (rendered as `#${key}`); i18n'd via
 *   `t('nav.${key}')`. Pass [] to hide the link row entirely.
 * - registerHref: absolute URL to send register/get-started clicks to.
 *   When omitted we use react-router navigate('/register'). Alpha
 *   subdomain passes 'https://agentprovision.com/register' so the
 *   auth flow always lives on the apex (PR #450 review BLOCKER B1).
 * - signInHref: same shape for sign-in.
 */
export default function LandingNav({ links = DEFAULT_LINKS, registerHref, signInHref } = {}) {
  const { t } = useTranslation('landing');
  const navigate = useNavigate();
  const [scrolled, setScrolled] = useState(false);
  const prefersReducedMotion = useReducedMotion();

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 50);
    window.addEventListener('scroll', handler, { passive: true });
    return () => window.removeEventListener('scroll', handler);
  }, []);

  const onSignIn = () => {
    track('cta_sign_in_click', { location: 'nav' });
    if (signInHref) {
      window.location.assign(signInHref);
    } else {
      navigate('/login');
    }
  };
  const onGetStarted = () => {
    track('cta_get_started_click', { location: 'nav' });
    if (registerHref) {
      window.location.assign(registerHref);
    } else {
      navigate('/register');
    }
  };

  return (
    <motion.nav
      className={`landing-nav ${scrolled ? 'landing-nav--scrolled' : ''}`}
      initial={prefersReducedMotion ? {} : { opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: prefersReducedMotion ? 0 : 0.4 }}
    >
      <div className="landing-nav__inner">
        <span className="landing-nav__logo">AgentProvision</span>

        <div className="landing-nav__links">
          {links.map((key, i) => (
            <motion.a
              key={key}
              href={`#${key}`}
              className="landing-nav__link"
              initial={prefersReducedMotion ? {} : { opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: prefersReducedMotion ? 0 : i * 0.06 + 0.2 }}
            >
              {t(`nav.${key}`)}
            </motion.a>
          ))}
        </div>

        <div className="landing-nav__actions">
          <button className="landing-nav__signin" onClick={onSignIn}>
            {t('nav.signIn')}
          </button>
          <motion.button
            className="landing-nav__cta"
            onClick={onGetStarted}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}
            transition={{ type: 'spring', stiffness: 400, damping: 17 }}
          >
            {t('nav.getStarted')}
          </motion.button>
        </div>
      </div>
    </motion.nav>
  );
}
