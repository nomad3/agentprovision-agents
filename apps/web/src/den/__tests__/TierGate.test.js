/**
 * TierGate renders children only when the user's tier ≥ min.
 */
import { render, screen } from '@testing-library/react';

import { TierGate } from '../TierGate';

jest.mock('../useTier', () => ({
  useTier: jest.fn(),
}));

const { useTier } = require('../useTier');

describe('TierGate', () => {
  beforeEach(() => jest.clearAllMocks());

  test('renders children when tier >= min', () => {
    useTier.mockReturnValue([3]);
    render(<TierGate min={2}>visible content</TierGate>);
    expect(screen.getByText('visible content')).toBeInTheDocument();
  });

  test('renders fallback when tier < min', () => {
    useTier.mockReturnValue([1]);
    render(<TierGate min={3} fallback={<span>not yet</span>}>blocked</TierGate>);
    expect(screen.queryByText('blocked')).not.toBeInTheDocument();
    expect(screen.getByText('not yet')).toBeInTheDocument();
  });

  test('renders nothing when tier < min and no fallback', () => {
    useTier.mockReturnValue([0]);
    const { container } = render(<TierGate min={5}>hidden</TierGate>);
    expect(container.firstChild).toBeNull();
  });

  test('boundary: exactly equal to min renders children', () => {
    useTier.mockReturnValue([2]);
    render(<TierGate min={2}>edge case</TierGate>);
    expect(screen.getByText('edge case')).toBeInTheDocument();
  });
});
