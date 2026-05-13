import { render, screen } from '@testing-library/react';
import AlphaPlatformPower from '../AlphaPlatformPower';

beforeAll(() => {
  global.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

test('renders three platform pillars', () => {
  render(<AlphaPlatformPower />);
  expect(screen.getByText(/Reinforcement Learning/)).toBeInTheDocument();
  expect(screen.getByText(/Memory-first/)).toBeInTheDocument();
  expect(screen.getByText(/Temporal workflows/)).toBeInTheDocument();
});

test('has a section anchor for #platform (used by reused LandingNav)', () => {
  render(<AlphaPlatformPower />);
  // The shared nav links to #platform; alpha LandingPage relies on
  // this id existing inside this section.
  const section = document.getElementById('platform');
  expect(section).not.toBeNull();
});
