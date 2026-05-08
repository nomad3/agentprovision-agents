import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const apiJsonMock = vi.fn();

vi.mock('../../api', () => ({
  apiJson: (...args) => apiJsonMock(...args),
}));

import WorkflowSuggestions from '../WorkflowSuggestions';

beforeEach(() => {
  apiJsonMock.mockReset();
});

const buildSuggestion = (overrides = {}) => ({
  pattern: 'gmail-then-jira',
  apps: ['Gmail', 'Jira'],
  suggestion: 'Auto-create a Jira ticket whenever a customer email matches "support".',
  frequency: 12,
  workflow_template: { name: 'Gmail to Jira', steps: [] },
  ...overrides,
});

describe('WorkflowSuggestions', () => {
  it('renders nothing when not visible', () => {
    const { container } = render(<WorkflowSuggestions visible={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
    expect(apiJsonMock).not.toHaveBeenCalled();
  });

  it('shows the loading state while fetching patterns', async () => {
    let resolveFn;
    apiJsonMock.mockReturnValue(new Promise((r) => { resolveFn = r; }));
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    expect(screen.getByText(/analyzing your patterns/i)).toBeInTheDocument();
    resolveFn({ suggestions: [], patterns: {}, activity_count: 0, period_days: 7 });
    await waitFor(() => expect(screen.queryByText(/analyzing your patterns/i)).not.toBeInTheDocument());
  });

  it('fetches patterns over the last 7 days when shown', async () => {
    apiJsonMock.mockResolvedValue({ suggestions: [], patterns: {}, activity_count: 0, period_days: 7 });
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/activities/patterns?days=7');
    });
  });

  it('renders the empty state when no suggestions are returned', async () => {
    apiJsonMock.mockResolvedValue({ suggestions: [], patterns: {}, activity_count: 0, period_days: 7 });
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/no patterns detected yet/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/keep using your apps/i)).toBeInTheDocument();
  });

  it('renders a suggestion card with apps, description, and frequency', async () => {
    apiJsonMock.mockResolvedValue({
      suggestions: [buildSuggestion()],
      patterns: {},
      activity_count: 100,
      period_days: 7,
    });
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText('Gmail')).toBeInTheDocument());
    expect(screen.getByText('Jira')).toBeInTheDocument();
    expect(screen.getByText(/Auto-create a Jira ticket/)).toBeInTheDocument();
    expect(screen.getByText(/12x in the last week/)).toBeInTheDocument();
  });

  it('creates a workflow when "Automate this" is clicked, posting the template', async () => {
    apiJsonMock.mockResolvedValueOnce({
      suggestions: [buildSuggestion()],
      patterns: {},
      activity_count: 10,
      period_days: 7,
    });
    apiJsonMock.mockResolvedValueOnce({ id: 'wf-1' });
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Automate this/)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Automate this/));
    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/dynamic-workflows', {
        method: 'POST',
        body: JSON.stringify({ name: 'Gmail to Jira', steps: [] }),
      });
    });
    // The card should be removed from the list
    await waitFor(() => {
      expect(screen.queryByText(/Automate this/)).not.toBeInTheDocument();
    });
  });

  it('shows a "Creating..." label while the workflow POST is in flight', async () => {
    apiJsonMock.mockResolvedValueOnce({
      suggestions: [buildSuggestion()],
      patterns: {},
      activity_count: 5,
      period_days: 7,
    });
    let resolveCreate;
    apiJsonMock.mockReturnValueOnce(new Promise((r) => { resolveCreate = r; }));
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Automate this/)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Automate this/));
    await waitFor(() => expect(screen.getByText(/Creating\.\.\./)).toBeInTheDocument());
    resolveCreate({ id: 'wf-2' });
    await waitFor(() => expect(screen.queryByText(/Creating\.\.\./)).not.toBeInTheDocument());
  });

  it('keeps the suggestion in the list when workflow creation fails', async () => {
    apiJsonMock.mockResolvedValueOnce({
      suggestions: [buildSuggestion()],
      patterns: {},
      activity_count: 5,
      period_days: 7,
    });
    apiJsonMock.mockRejectedValueOnce(new Error('boom'));
    // Suppress the expected console.error
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Automate this/)).toBeInTheDocument());
    fireEvent.click(screen.getByText(/Automate this/));
    await waitFor(() => expect(screen.getByText(/Automate this/)).toBeInTheDocument());
    expect(screen.getByText(/Auto-create a Jira ticket/)).toBeInTheDocument();
    errSpy.mockRestore();
  });

  it('renders the daily rhythm section when time_of_day buckets exist', async () => {
    apiJsonMock.mockResolvedValue({
      suggestions: [],
      patterns: {
        time_of_day: {
          morning: [{ app: 'Gmail', count: 24 }],
          afternoon: [{ app: 'Jira', count: 11 }],
        },
      },
      activity_count: 35,
      period_days: 7,
    });
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/your daily rhythm/i)).toBeInTheDocument());
    expect(screen.getByText('morning')).toBeInTheDocument();
    expect(screen.getByText('afternoon')).toBeInTheDocument();
    expect(screen.getByText(/Gmail \(24\)/)).toBeInTheDocument();
    expect(screen.getByText(/Jira \(11\)/)).toBeInTheDocument();
  });

  it('renders the activity footer with totals', async () => {
    apiJsonMock.mockResolvedValue({
      suggestions: [],
      patterns: {},
      activity_count: 145,
      period_days: 7,
    });
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/145 events tracked over 7 days/)).toBeInTheDocument());
  });

  it('triggers onClose when the close button is clicked', async () => {
    apiJsonMock.mockResolvedValue({ suggestions: [], patterns: {}, activity_count: 0, period_days: 7 });
    const onClose = vi.fn();
    render(<WorkflowSuggestions visible={true} onClose={onClose} />);
    await waitFor(() => expect(screen.getByText(/no patterns detected/i)).toBeInTheDocument());
    fireEvent.click(document.querySelector('.notif-close'));
    expect(onClose).toHaveBeenCalled();
  });

  it('handles fetch errors and renders neither loading nor footer', async () => {
    apiJsonMock.mockRejectedValue(new Error('network down'));
    render(<WorkflowSuggestions visible={true} onClose={() => {}} />);
    await waitFor(() => expect(screen.queryByText(/analyzing/i)).not.toBeInTheDocument());
    expect(screen.queryByText(/events tracked/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/your daily rhythm/i)).not.toBeInTheDocument();
  });
});
