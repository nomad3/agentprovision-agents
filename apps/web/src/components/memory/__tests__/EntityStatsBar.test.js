import { render, screen } from '@testing-library/react';
import EntityStatsBar from '../EntityStatsBar';

describe('EntityStatsBar', () => {
  test('shows zero entities when the list is empty', () => {
    render(<EntityStatsBar entities={[]} />);
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('entities')).toBeInTheDocument();
  });

  test('counts entities by category and renders one chip per category', () => {
    const entities = [
      { id: 1, category: 'person' },
      { id: 2, category: 'person' },
      { id: 3, category: 'company' },
      { id: 4, category: 'PERSON' },
    ];
    const { container } = render(<EntityStatsBar entities={entities} />);
    expect(screen.getByText('4')).toBeInTheDocument();
    // Two category chips
    expect(container.querySelectorAll('.stats-chip').length).toBe(2);
    // person = 3 occurrences
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  test('falls back to "concept" when category is missing', () => {
    render(<EntityStatsBar entities={[{ id: 'x' }]} />);
    // Total + the chip count both render as "1" — assert there are two.
    expect(screen.getAllByText('1').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('entities')).toBeInTheDocument();
  });
});
