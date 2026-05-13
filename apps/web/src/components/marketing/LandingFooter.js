import { useTranslation } from 'react-i18next';
import { FiGithub, FiTwitter, FiLinkedin } from 'react-icons/fi';

const DEFAULT_LINKS = [
  { key: 'platform', href: '#platform' },
  { key: 'features', href: '#features' },
  // TODO: wire real /docs + /github routes
  { key: 'docs', href: '#', preventDefault: true },
  { key: 'github', href: '#', preventDefault: true },
];

/**
 * Shared footer for marketing pages.
 *
 * Props:
 * - links: array of `{key, href, preventDefault?}`. `key` is the i18n
 *   key under `footer.links.${key}`. Alpha landing overrides this with
 *   anchors that actually exist on the page (commands, platform, etc.)
 *   so reused links aren't dead. PR #450 review IMPORTANT I1.
 */
export default function LandingFooter({ links = DEFAULT_LINKS } = {}) {
  const { t } = useTranslation('landing');
  const year = new Date().getFullYear();

  return (
    <footer className="landing-footer">
      <div className="landing-footer__inner">
        <div className="landing-footer__brand">
          <span className="landing-footer__logo">AgentProvision</span>
          <p className="landing-footer__tagline">{t('footer.tagline')}</p>
        </div>

        <nav className="landing-footer__nav">
          {links.map(({ key, href, preventDefault }) => (
            <a
              key={key}
              href={href}
              className="landing-footer__link"
              onClick={preventDefault ? (e) => e.preventDefault() : undefined}
            >
              {t(`footer.links.${key}`)}
            </a>
          ))}
        </nav>

        <div className="landing-footer__social">
          <a href="#" className="landing-footer__social-link" aria-label="GitHub" onClick={e => e.preventDefault()}><FiGithub size={20} /></a>
          <a href="#" className="landing-footer__social-link" aria-label="Twitter" onClick={e => e.preventDefault()}><FiTwitter size={20} /></a>
          <a href="#" className="landing-footer__social-link" aria-label="LinkedIn" onClick={e => e.preventDefault()}><FiLinkedin size={20} /></a>
        </div>
      </div>
      <p className="landing-footer__copy">{t('footer.copy', { year })}</p>
    </footer>
  );
}
