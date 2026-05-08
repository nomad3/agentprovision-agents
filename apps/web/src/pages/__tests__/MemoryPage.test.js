import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import MemoryPage from '../MemoryPage';

// ── Boundary mocks ────────────────────────────────────────────────────
jest.mock('../../services/memory', () => ({
  __esModule: true,
  memoryService: {
    getEntities: jest.fn(),
    searchEntities: jest.fn(),
    createEntity: jest.fn(),
    updateEntity: jest.fn(),
    deleteEntity: jest.fn(),
    bulkDeleteEntities: jest.fn(),
    updateEntityStatus: jest.fn(),
    scoreEntity: jest.fn(),
  },
}));
jest.mock('../../services/api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));

jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

// Sub-component tabs render arbitrary content; we just want a placeholder
// so the parent's tab switch is observable.
jest.mock('../../components/memory/OverviewTab', () => () => (
  <div data-testid="overview-tab" />
));
jest.mock('../../components/memory/MemoriesTab', () => () => (
  <div data-testid="memories-tab" />
));
jest.mock('../../components/memory/EpisodesTab', () => () => (
  <div data-testid="episodes-tab" />
));
jest.mock('../../components/memory/RelationsTab', () => () => (
  <div data-testid="relations-tab" />
));
jest.mock('../../components/memory/ActivityFeed', () => () => (
  <div data-testid="activity-feed" />
));
jest.mock('../../components/memory/EntityStatsBar', () => () => (
  <div data-testid="entity-stats-bar" />
));
jest.mock('../../components/memory/EntityCreateModal', () => ({ show, onClose }) =>
  show ? (
    <div data-testid="entity-create-modal">
      <button type="button" onClick={onClose}>close-modal</button>
    </div>
  ) : null,
);
jest.mock('../../components/memory/EntityCard', () => ({ entity }) => (
  <div data-testid={`entity-card-${entity.id}`}>{entity.name}</div>
));

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => {
      if (typeof opts === 'string') return opts;
      if (opts && typeof opts === 'object' && !Array.isArray(opts)) {
        // Crude {{var}} interpolation
        const fallback = key;
        return Object.keys(opts).reduce(
          (acc, k) => acc.replace(`{{${k}}}`, opts[k]),
          fallback,
        );
      }
      return key;
    },
  }),
}));

const { memoryService } = require('../../services/memory');

const sampleEntities = [
  { id: 'e-1', name: 'Brett', category: 'person', status: 'active' },
  { id: 'e-2', name: 'Aremko', category: 'organization', status: 'active' },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <MemoryPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  memoryService.getEntities.mockResolvedValue(sampleEntities);
  memoryService.searchEntities.mockResolvedValue([sampleEntities[0]]);
  memoryService.createEntity.mockResolvedValue({});
  memoryService.deleteEntity.mockResolvedValue({});
  memoryService.bulkDeleteEntities.mockResolvedValue({});
});

describe('MemoryPage', () => {
  test('renders the page header and default Overview tab', async () => {
    renderPage();
    expect(await screen.findByText('title')).toBeInTheDocument();
    // Overview is the default tab; the OverviewTab stub renders.
    expect(await screen.findByTestId('overview-tab')).toBeInTheDocument();
  });

  test('switches to Entities tab and loads entities', async () => {
    renderPage();
    await screen.findByTestId('overview-tab');
    fireEvent.click(screen.getByRole('tab', { name: 'tabs.entities' }));
    await waitFor(() => expect(memoryService.getEntities).toHaveBeenCalled());
    expect(await screen.findByTestId('entity-card-e-1')).toBeInTheDocument();
    expect(screen.getByTestId('entity-card-e-2')).toBeInTheDocument();
  });

  test('search input triggers searchEntities on Enter key', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'tabs.entities' }));
    await screen.findByTestId('entity-card-e-1');
    const search = screen.getByPlaceholderText('entities.searchPlaceholder');
    fireEvent.change(search, { target: { value: 'Brett' } });
    fireEvent.keyDown(search, { key: 'Enter', code: 'Enter' });
    await waitFor(() => {
      expect(memoryService.searchEntities).toHaveBeenCalledWith(
        'Brett',
        expect.any(Object),
      );
    });
  });

  test('opens the create-entity modal', async () => {
    renderPage();
    await screen.findByText('title');
    fireEvent.click(screen.getByRole('button', { name: /addEntity/i }));
    expect(await screen.findByTestId('entity-create-modal')).toBeInTheDocument();
  });

  test('switches to Memories tab and renders MemoriesTab', async () => {
    renderPage();
    await screen.findByTestId('overview-tab');
    fireEvent.click(screen.getByRole('tab', { name: 'tabs.memories' }));
    expect(await screen.findByTestId('memories-tab')).toBeInTheDocument();
  });

  test('switches to Episodes tab and renders EpisodesTab', async () => {
    renderPage();
    await screen.findByTestId('overview-tab');
    fireEvent.click(screen.getByRole('tab', { name: 'Episodes' }));
    expect(await screen.findByTestId('episodes-tab')).toBeInTheDocument();
  });

  test('switches to Relations tab and renders RelationsTab', async () => {
    renderPage();
    await screen.findByTestId('overview-tab');
    fireEvent.click(screen.getByRole('tab', { name: 'tabs.relations' }));
    expect(await screen.findByTestId('relations-tab')).toBeInTheDocument();
  });

  test('switches to Activity tab and renders ActivityFeed', async () => {
    renderPage();
    await screen.findByTestId('overview-tab');
    fireEvent.click(screen.getByRole('tab', { name: 'tabs.activity' }));
    expect(await screen.findByTestId('activity-feed')).toBeInTheDocument();
  });

  test('Entities tab renders empty when getEntities returns []', async () => {
    memoryService.getEntities.mockResolvedValue([]);
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'tabs.entities' }));
    await waitFor(() => expect(memoryService.getEntities).toHaveBeenCalled());
    expect(screen.queryByTestId('entity-card-e-1')).not.toBeInTheDocument();
  });

  test('renders all 7 tabs', async () => {
    renderPage();
    await screen.findByTestId('overview-tab');
    const expectedTabs = [
      'tabs.overview', 'tabs.entities', 'tabs.relations',
      'tabs.memories', 'Episodes', 'tabs.activity', 'tabs.import',
    ];
    expectedTabs.forEach(tab => {
      expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument();
    });
  });

  test('survives a getEntities error without crashing', async () => {
    memoryService.getEntities.mockRejectedValue(new Error('network'));
    const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    renderPage();
    fireEvent.click(screen.getByRole('tab', { name: 'tabs.entities' }));
    await waitFor(() => expect(memoryService.getEntities).toHaveBeenCalled());
    // Page header still rendered; no crash.
    expect(screen.getByText('title')).toBeInTheDocument();
    errSpy.mockRestore();
  });
});
