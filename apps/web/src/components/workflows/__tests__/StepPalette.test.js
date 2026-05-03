import { render, screen, fireEvent } from '@testing-library/react';
import StepPalette from '../StepPalette';

// Stub react-i18next so the palette renders the raw keys, which we
// can match against deterministically.
jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k, opts) => (opts?.count != null ? `${k}:${opts.count}` : k) }),
}));

describe('StepPalette', () => {
  test('renders default palette categories', () => {
    render(<StepPalette mcpTools={[]} />);
    expect(screen.getByText('Scheduled (Cron)')).toBeInTheDocument();
    expect(screen.getByText('Manual')).toBeInTheDocument();
    expect(screen.getByText('Condition (If/Else)')).toBeInTheDocument();
    expect(screen.getByText('Wait / Delay')).toBeInTheDocument();
    expect(screen.getByText('Human Approval')).toBeInTheDocument();
  });

  test('shows MCP tools when provided and humanizes the names', () => {
    render(<StepPalette mcpTools={[{ name: 'gmail_send' }, 'slack_post']} />);
    expect(screen.getByText('Gmail Send')).toBeInTheDocument();
    expect(screen.getByText('Slack Post')).toBeInTheDocument();
  });

  test('drag-start writes the item JSON to the dataTransfer', () => {
    render(<StepPalette mcpTools={[]} />);
    const item = screen.getByText('Manual');
    const setData = jest.fn();
    const dataTransfer = { setData, effectAllowed: '' };
    fireEvent.dragStart(item, { dataTransfer });
    expect(setData).toHaveBeenCalledWith(
      'application/workflow-step',
      expect.stringContaining('"subtype":"manual"')
    );
  });
});
