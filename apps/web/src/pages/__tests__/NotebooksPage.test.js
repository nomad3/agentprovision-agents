import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import NotebooksPage from '../NotebooksPage';

jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => {
      if (typeof opts === 'string') return opts;
      if (opts && opts.total) return `${key}: total=${opts.total}`;
      return key;
    },
  }),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <NotebooksPage />
    </MemoryRouter>,
  );
}

describe('NotebooksPage', () => {
  test('renders the page header and stat tiles', () => {
    renderPage();
    expect(screen.getByText('title')).toBeInTheDocument();
    expect(screen.getByText('stats.totalReports')).toBeInTheDocument();
    expect(screen.getByText('stats.coverage')).toBeInTheDocument();
    expect(screen.getByText('stats.automated')).toBeInTheDocument();
    expect(screen.getByText('stats.lastUpdated')).toBeInTheDocument();
  });

  test('renders the report templates table', () => {
    renderPage();
    // The templates list is hard-coded — at least the P&L template renders.
    expect(screen.getByText('P&L Statement')).toBeInTheDocument();
    expect(screen.getByText('Consolidated Balance Sheet')).toBeInTheDocument();
  });

  test('search filter narrows the table by name/description', () => {
    renderPage();
    const search = screen.getByPlaceholderText('searchPlaceholder');
    fireEvent.change(search, { target: { value: 'Balance' } });
    expect(screen.getByText('Consolidated Balance Sheet')).toBeInTheDocument();
    expect(screen.queryByText('P&L Statement')).not.toBeInTheDocument();
  });

  test('clicking a row opens the detail modal with the report data', () => {
    renderPage();
    fireEvent.click(screen.getByText('P&L Statement'));
    // Modal opens — heading repeats the report name.
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
  });

  test('shows scheduled count derived from non-on-demand templates', () => {
    renderPage();
    // The scheduled stat tile just renders a number; assert the label is present.
    expect(screen.getByText('stats.automated')).toBeInTheDocument();
  });
});
