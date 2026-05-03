import { render, screen, fireEvent } from '@testing-library/react';
import TestConsole from '../TestConsole';

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k, opts) => (opts?.count != null ? `${k}:${opts.count}` : k) }),
}));

describe('TestConsole', () => {
  test('renders loading state when results are missing', () => {
    render(<TestConsole results={null} onClose={() => {}} />);
    expect(screen.getByText(/builder.testConsole.running/)).toBeInTheDocument();
  });

  test('renders the validation error list when present', () => {
    render(
      <TestConsole
        results={{
          validation_errors: ['step xyz missing tool', 'cycle detected'],
          steps_planned: [],
          step_count: 0,
        }}
        onClose={() => {}}
      />
    );
    expect(screen.getByText(/step xyz missing tool/)).toBeInTheDocument();
    expect(screen.getByText(/cycle detected/)).toBeInTheDocument();
    expect(screen.getByText(/builder.testConsole.errorsFound/)).toBeInTheDocument();
  });

  test('renders the planned steps and integration list when valid', () => {
    render(
      <TestConsole
        results={{
          steps_planned: [{ type: 'mcp_tool' }, 'send_email'],
          step_count: 2,
          integrations_required: ['gmail', 'slack'],
          validation_errors: [],
        }}
        onClose={() => {}}
      />
    );
    expect(screen.getByText('mcp_tool')).toBeInTheDocument();
    expect(screen.getByText('send_email')).toBeInTheDocument();
    expect(screen.getByText('gmail')).toBeInTheDocument();
    expect(screen.getByText('slack')).toBeInTheDocument();
    expect(screen.getByText(/builder.testConsole.valid/)).toBeInTheDocument();
  });

  test('clicking the close icon fires onClose', () => {
    const onClose = jest.fn();
    const { container } = render(<TestConsole results={null} onClose={onClose} />);
    const closer = container.querySelector('.test-console-header svg');
    fireEvent.click(closer);
    expect(onClose).toHaveBeenCalled();
  });
});
