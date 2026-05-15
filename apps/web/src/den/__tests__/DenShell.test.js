/**
 * DenShell — tier-aware density rendering of the 3-zone shell.
 *
 * Tier 0: welcome card visible, rail/right/drawer hidden.
 * Tier 1: rail visible, right + drawer still hidden.
 * Tier 2+3: rail + right visible, drawer hidden.
 * Tier 4+: rail + right + drawer all visible.
 */
import { render, screen } from '@testing-library/react';

import { DenShell } from '../DenShell';

jest.mock('../useTier');
const { useTier } = require('../useTier');
const { getCapabilities } = require('../tierFeatures');

function mountWithTier(tier, props = {}) {
  useTier.mockReturnValue([tier, jest.fn(), getCapabilities(tier)]);
  return render(<DenShell messages={[]} {...props} />);
}

describe('DenShell tier-aware rendering', () => {
  beforeEach(() => jest.clearAllMocks());

  test('tier 0 — welcome card visible, no rail/right/drawer', () => {
    mountWithTier(0);
    expect(screen.getByTestId('welcome-card')).toBeInTheDocument();
    expect(screen.queryByLabelText(/Den navigation/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Context panel/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Live terminal/i)).not.toBeInTheDocument();
  });

  test('tier 0 — show what this can become button opens picker', () => {
    mountWithTier(0);
    expect(screen.getByTestId('show-what-this-can-become')).toBeInTheDocument();
  });

  test('tier 0 — welcome card disappears once there are messages', () => {
    mountWithTier(0, { messages: [{ event_id: '1', role: 'user', text: 'hi' }] });
    expect(screen.queryByTestId('welcome-card')).not.toBeInTheDocument();
  });

  test('tier 1 — rail visible, right panel hidden (rail-only addition)', () => {
    mountWithTier(1);
    expect(screen.getByLabelText(/Den navigation/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Context panel/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Live terminal/i)).not.toBeInTheDocument();
  });

  test('tier 2 — rail + right panel visible, drawer hidden', () => {
    mountWithTier(2);
    expect(screen.getByLabelText(/Den navigation/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Context panel/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Live terminal/i)).not.toBeInTheDocument();
  });

  test('tier 4 — drawer becomes visible', () => {
    mountWithTier(4);
    expect(screen.getByLabelText(/Den navigation/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Context panel/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Live terminal/i)).toBeInTheDocument();
  });

  test('shell carries data-tier attribute for css + a11y', () => {
    mountWithTier(3);
    const shell = screen.getByTestId('den-shell');
    expect(shell).toHaveAttribute('data-tier', '3');
  });
});
