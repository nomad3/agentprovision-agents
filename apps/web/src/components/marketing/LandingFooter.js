import { FiGithub, FiTwitter, FiLinkedin } from 'react-icons/fi';

export default function LandingFooter() {
  return (
    <footer className="landing-footer">
      <div className="landing-footer__inner">
        <div className="landing-footer__brand">
          <span className="landing-footer__logo">AgentProvision</span>
          <p className="landing-footer__tagline">Enterprise AI orchestration, built for teams that ship.</p>
        </div>

        <nav className="landing-footer__nav">
          <a href="#platform" className="landing-footer__link">Platform</a>
          <a href="#features" className="landing-footer__link">Features</a>
          <a href="#" className="landing-footer__link">Docs</a>
          <a href="#" className="landing-footer__link">GitHub</a>
        </nav>

        <div className="landing-footer__social">
          <a href="#" className="landing-footer__social-link" aria-label="GitHub"><FiGithub size={20} /></a>
          <a href="#" className="landing-footer__social-link" aria-label="Twitter"><FiTwitter size={20} /></a>
          <a href="#" className="landing-footer__social-link" aria-label="LinkedIn"><FiLinkedin size={20} /></a>
        </div>
      </div>
      <p className="landing-footer__copy">© {new Date().getFullYear()} AgentProvision. All rights reserved.</p>
    </footer>
  );
}
