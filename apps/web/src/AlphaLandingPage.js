/**
 * `alpha.agentprovision.com` landing page — focused on the CLI as a
 * product. Reuses LandingNav + LandingFooter + CTASection from the
 * main agentprovision.com landing, with four alpha-specific sections
 * in between.
 *
 * Wired at `/alpha` on the existing frontend (App.js); the
 * `alpha.agentprovision.com` subdomain points to the same SPA and the
 * router resolves the path. No new Cloudflare tunnel required.
 */
import React from 'react';
import LandingNav from './components/marketing/LandingNav';
import LandingFooter from './components/marketing/LandingFooter';
import CTASection from './components/marketing/CTASection';
import AlphaHero from './components/marketing/alpha/AlphaHero';
import AlphaDifferentiators from './components/marketing/alpha/AlphaDifferentiators';
import AlphaCommands from './components/marketing/alpha/AlphaCommands';
import AlphaPlatformPower from './components/marketing/alpha/AlphaPlatformPower';
import './LandingPage.css'; // shared design tokens + nav/footer/cta styles
import './AlphaLandingPage.css';

export default function AlphaLandingPage() {
  return (
    <>
      <LandingNav />
      <main className="alpha-landing">
        <AlphaHero />
        <AlphaDifferentiators />
        <AlphaCommands />
        <AlphaPlatformPower />
        <CTASection />
      </main>
      <LandingFooter />
    </>
  );
}
