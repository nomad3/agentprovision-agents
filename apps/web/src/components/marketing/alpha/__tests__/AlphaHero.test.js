import { render, screen } from '@testing-library/react';
import AlphaHero from '../AlphaHero';

// Mock the analytics module so its track() calls during render don't
// try to load Plausible in jsdom.
jest.mock('../../../../services/marketingAnalytics', () => ({
  track: jest.fn(),
}));

test('renders the hero headline', () => {
  render(<AlphaHero />);
  expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
});

test('renders the copyable install command', () => {
  render(<AlphaHero />);
  expect(
    screen.getByText(/curl -fsSL https:\/\/agentprovision\.com\/install\.sh \| sh/)
  ).toBeInTheDocument();
  // Copy button is accessible by label.
  expect(
    screen.getByRole('button', { name: /copy install command/i })
  ).toBeInTheDocument();
});

test('register CTA links to the apex (not subdomain-relative)', () => {
  // PR #450 BLOCKER B1: alpha CTAs must point at the apex so auth
  // flows resolve. Locks the contract — the wrapping <a> href must
  // be the absolute agentprovision.com URL, not a relative /register
  // that would 404 on the alpha subdomain.
  render(<AlphaHero />);
  const cta = screen.getByText(/get started free/i).closest('a');
  expect(cta).not.toBeNull();
  expect(cta.getAttribute('href')).toBe('https://agentprovision.com/register');
});

test('GitHub link opens in new tab', () => {
  render(<AlphaHero />);
  const gh = screen.getByText(/view on github/i).closest('a');
  expect(gh).not.toBeNull();
  expect(gh.getAttribute('target')).toBe('_blank');
  expect(gh.getAttribute('rel')).toMatch(/noopener/);
});
