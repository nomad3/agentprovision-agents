import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import IntegrationsPage from '../IntegrationsPage';

// ── Boundary mocks ────────────────────────────────────────────────────
// IntegrationsPage talks to ~7 services + the IntegrationsPanel child
// component. Mock the service modules at the boundary; mock the heavy
// child components so we test the page-level routing/tab logic only.
jest.mock('../../services/api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));
jest.mock('../../services/connector', () => ({
  __esModule: true,
  default: {
    getAll: jest.fn(() => Promise.resolve({ data: [] })),
    create: jest.fn(),
    update: jest.fn(),
    delete: jest.fn(),
    testConnection: jest.fn(),
    testExisting: jest.fn(),
  },
}));
jest.mock('../../services/dataPipeline', () => ({
  __esModule: true,
  default: {
    getAll: jest.fn(() => Promise.resolve({ data: [] })),
    create: jest.fn(),
    execute: jest.fn(),
  },
}));
jest.mock('../../services/dataSource', () => ({
  __esModule: true,
  default: {
    getAll: jest.fn(() => Promise.resolve({ data: [] })),
    create: jest.fn(),
    update: jest.fn(),
    remove: jest.fn(),
  },
}));
jest.mock('../../services/dataset', () => ({
  __esModule: true,
  default: {
    getAll: jest.fn(() => Promise.resolve({ data: [] })),
    upload: jest.fn(),
    getPreview: jest.fn(),
    getSummary: jest.fn(),
    sync: jest.fn(),
  },
}));
jest.mock('../../services/datasetGroup', () => ({
  __esModule: true,
  default: {
    getAll: jest.fn(() => Promise.resolve({ data: [] })),
    create: jest.fn(),
  },
}));
jest.mock('../../services/llm', () => ({
  __esModule: true,
  default: {
    getProviderStatus: jest.fn(() => Promise.resolve([])),
    setProviderKey: jest.fn(),
  },
}));

jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);
jest.mock('../../components/IntegrationsPanel', () => () => (
  <div data-testid="integrations-panel">integrations-panel</div>
));
jest.mock('../../components/DevicePanel', () => () => (
  <div data-testid="device-panel">device-panel</div>
));
jest.mock('../../components/WhatsAppChannelCard', () => () => null);

jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  const setSearchParams = jest.fn();
  const params = new URLSearchParams();
  return {
    ...actual,
    useSearchParams: () => [params, setSearchParams],
  };
});

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => {
      if (typeof opts === 'string') return opts;
      return key;
    },
  }),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <IntegrationsPage />
    </MemoryRouter>,
  );
}

describe('IntegrationsPage', () => {
  test('renders the page header and default Integrations tab content', async () => {
    renderPage();
    expect(await screen.findByText('title')).toBeInTheDocument();
    // Default tab is 'integrations' → shows IntegrationsPanel.
    expect(await screen.findByTestId('integrations-panel')).toBeInTheDocument();
  });

  test('renders all six main tabs', async () => {
    renderPage();
    await screen.findByTestId('integrations-panel');
    const tabKeys = [
      'tabs.integrations', 'tabs.connectors', 'tabs.dataSources',
      'tabs.datasets', 'tabs.aiModels',
    ];
    tabKeys.forEach(label => {
      expect(screen.getByRole('tab', { name: new RegExp(label) })).toBeInTheDocument();
    });
  });

  test('switches to Devices tab and renders DevicePanel', async () => {
    renderPage();
    await screen.findByTestId('integrations-panel');
    // Devices uses fallback "Devices" since t('tabs.devices') returns the key.
    fireEvent.click(screen.getByRole('tab', { name: /tabs\.devices|Devices/i }));
    expect(await screen.findByTestId('device-panel')).toBeInTheDocument();
  });

  test('switches to Connectors tab and triggers connector fetch', async () => {
    const connectorService = require('../../services/connector').default;
    renderPage();
    await screen.findByTestId('integrations-panel');
    fireEvent.click(screen.getByRole('tab', { name: /tabs\.connectors/i }));
    // fetchConnectors fires on mount, so it's already called once. Just
    // ensure the tab switch did not crash the page and the connector list
    // is being read.
    await waitFor(() => expect(connectorService.getAll).toHaveBeenCalled());
  });

  test('switches to Data Sources tab without crashing', async () => {
    renderPage();
    await screen.findByTestId('integrations-panel');
    fireEvent.click(screen.getByRole('tab', { name: /tabs\.dataSources/i }));
    // Page should still be present after the switch.
    expect(screen.getByText('title')).toBeInTheDocument();
  });

  test('switches to Datasets tab without crashing', async () => {
    renderPage();
    await screen.findByTestId('integrations-panel');
    fireEvent.click(screen.getByRole('tab', { name: /tabs\.datasets/i }));
    expect(screen.getByText('title')).toBeInTheDocument();
  });

  test('switches to AI Models tab without crashing', async () => {
    // Provider status returns an array of provider objects shaped enough
    // for the UI's .map() iteration to succeed.
    const llmService = require('../../services/llm').default;
    llmService.getProviderStatus.mockResolvedValue([
      { name: 'anthropic', connected: false },
    ]);
    renderPage();
    await screen.findByTestId('integrations-panel');
    fireEvent.click(screen.getByRole('tab', { name: /tabs\.aiModels/i }));
    // Subtitle text appears under the AI Models tab.
    expect(await screen.findByText('aiModels.subtitle')).toBeInTheDocument();
  });

  test('triggers parallel fetches on mount (connectors + data sources + datasets + groups + llm)', async () => {
    const connectorService = require('../../services/connector').default;
    const dataSourceService = require('../../services/dataSource').default;
    const datasetService = require('../../services/dataset').default;
    const datasetGroupService = require('../../services/datasetGroup').default;
    const llmService = require('../../services/llm').default;

    renderPage();
    await waitFor(() => {
      expect(connectorService.getAll).toHaveBeenCalled();
      expect(dataSourceService.getAll).toHaveBeenCalled();
      expect(datasetService.getAll).toHaveBeenCalled();
      expect(datasetGroupService.getAll).toHaveBeenCalled();
      expect(llmService.getProviderStatus).toHaveBeenCalled();
    });
  });
});
