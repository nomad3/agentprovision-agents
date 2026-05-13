import { render, screen } from '@testing-library/react';
import AlphaDifferentiators from '../AlphaDifferentiators';

beforeAll(() => {
  // framer-motion uses IntersectionObserver for whileInView.
  global.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

test('renders the comparison table with header columns', () => {
  render(<AlphaDifferentiators />);
  // Table semantics — real <table>, not a faux grid.
  const table = screen.getByRole('table');
  expect(table).toBeInTheDocument();
  // Constrain text queries to the table — competitor names also
  // appear in the section heading + subtitle copy, which would
  // ambiguate getByText otherwise.
  const cols = ['Capability', 'alpha', 'Claude Code', 'Codex', 'Gemini CLI', 'Copilot CLI'];
  const headerCells = table.querySelectorAll('thead th');
  const headerText = Array.from(headerCells).map((c) => c.textContent.trim());
  cols.forEach((col) => expect(headerText).toContain(col));
});

test('renders all 8 capability rows', () => {
  render(<AlphaDifferentiators />);
  // Each capability has a unique bold title; spot-check the 8.
  expect(screen.getByText(/Multi-LLM orchestration/i)).toBeInTheDocument();
  expect(screen.getByText(/Durable tasks/i)).toBeInTheDocument();
  expect(screen.getByText(/Multi-tenant \+ RBAC/i)).toBeInTheDocument();
  expect(screen.getByText(/Cross-session memory/i)).toBeInTheDocument();
  expect(screen.getByText(/Multi-agent coalitions/i)).toBeInTheDocument();
  expect(screen.getByText(/Recipes \(Helm-charts for AI workflows\)/i)).toBeInTheDocument();
  expect(screen.getByText(/Live progress JSONL/i)).toBeInTheDocument();
  expect(screen.getByText(/Cost & token attribution/i)).toBeInTheDocument();
});

test('alpha column shows the check glyph at least 8 times (one per row)', () => {
  render(<AlphaDifferentiators />);
  // 8 capabilities, alpha=true for every row → at least 8 check glyphs.
  const checks = screen.getAllByText('✓');
  expect(checks.length).toBeGreaterThanOrEqual(8);
});
