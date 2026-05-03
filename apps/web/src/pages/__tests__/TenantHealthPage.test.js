import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

jest.mock('../../services/api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));
jest.mock('../../components/Layout', () => {
  const ReactInner = require('react');
  return {
    __esModule: true,
    default: ({ children }) => ReactInner.createElement('div', null, children),
  };
});

import TenantHealthPage from '../TenantHealthPage';
import api from '../../services/api';


const renderPage = () =>
  render(
    React.createElement(MemoryRouter, null, React.createElement(TenantHealthPage))
  );


describe('TenantHealthPage', () => {
  beforeEach(() => jest.clearAllMocks());

  test('renders rows with curated triage fields', async () => {
    api.get.mockResolvedValueOnce({
      data: {
        window_hours: 24,
        rows: [
          {
            tenant_id: 't-1',
            tenant_name: 'AcmeCorp',
            user_count: 3,
            active_agent_count: 5,
            turn_count_24h: 42,
            fallback_rate_24h: 0.12,
            chain_exhausted_24h: 1,
            last_activity_at: new Date(Date.now() - 5 * 60_000).toISOString(),
            primary_cli: 'copilot_cli',
          },
        ],
      },
    });

    renderPage();

    await waitFor(() => expect(screen.getByText('AcmeCorp')).toBeInTheDocument());
    expect(screen.getByText('GitHub Copilot CLI')).toBeInTheDocument();
    expect(screen.getByText('12.0%')).toBeInTheDocument();
    expect(screen.getByText('5m ago')).toBeInTheDocument();
  });

  test('marks stalled tenants (zero turns) and shows dash for fallback', async () => {
    api.get.mockResolvedValueOnce({
      data: {
        window_hours: 24,
        rows: [
          {
            tenant_id: 't-2',
            tenant_name: 'StalledTenant',
            user_count: 1,
            active_agent_count: 0,
            turn_count_24h: 0,
            fallback_rate_24h: 0.0,
            chain_exhausted_24h: 0,
            last_activity_at: null,
            primary_cli: null,
          },
        ],
      },
    });

    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText('StalledTenant')).toBeInTheDocument());
    expect(container.querySelector('.tenant-row-stalled')).not.toBeNull();
    expect(screen.getByText('never')).toBeInTheDocument();
  });

  test('shows superuser-required message on 403', async () => {
    api.get.mockRejectedValueOnce({ response: { status: 403 } });
    renderPage();
    await waitFor(() => expect(screen.getByText(/Superuser access required/i)).toBeInTheDocument());
  });
});
