import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MarketplaceSection from '../MarketplaceSection';
import api from '../../../services/api';

jest.mock('../../../services/api');

describe('MarketplaceSection', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders the empty state when there are no listings', async () => {
    api.get.mockResolvedValue({ data: [] });
    render(<MarketplaceSection />);
    expect(await screen.findByText(/No agents have been published/)).toBeInTheDocument();
  });

  test('renders one card per listing', async () => {
    api.get.mockResolvedValue({
      data: [
        {
          id: '1',
          name: 'Lead Hunter',
          protocol: 'mcp',
          description: 'Hunts leads',
          capabilities: ['search', 'enrich'],
          pricing_model: 'free',
          install_count: 12,
        },
        {
          id: '2',
          name: 'Email Drafter',
          protocol: 'webhook',
          description: '',
          capabilities: [],
          pricing_model: 'usage',
          price_per_call_usd: 0.05,
          install_count: 0,
        },
      ],
    });
    render(<MarketplaceSection />);
    expect(await screen.findByText('Lead Hunter')).toBeInTheDocument();
    expect(screen.getByText('Email Drafter')).toBeInTheDocument();
    expect(screen.getByText('mcp')).toBeInTheDocument();
    expect(screen.getByText(/Free/)).toBeInTheDocument();
    expect(screen.getByText(/usage/)).toBeInTheDocument();
  });

  test('subscribe posts to /marketplace/subscribe and shows the receipt', async () => {
    api.get.mockResolvedValue({
      data: [{ id: '1', name: 'X', protocol: 'mcp' }],
    });
    api.post.mockResolvedValue({ data: { status: 'approved' } });
    render(<MarketplaceSection />);
    fireEvent.click(await screen.findByText('Subscribe'));
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/marketplace/subscribe', { listing_id: '1' });
    });
    expect(await screen.findByText(/Agent added to External Agents/)).toBeInTheDocument();
  });

  test('shows an error notice when loading fails', async () => {
    api.get.mockRejectedValue({ response: { data: { detail: 'boom' } } });
    render(<MarketplaceSection />);
    expect(await screen.findByText('boom')).toBeInTheDocument();
  });
});
