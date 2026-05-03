import { render, screen, fireEvent } from '@testing-library/react';
import StepInspector from '../StepInspector';

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k) => k }),
}));

const mcpNode = (over = {}) => ({
  id: 'n1',
  type: 'stepNode',
  data: { step: { id: 's1', type: 'mcp_tool', tool: 'gmail.send', ...over } },
});

const triggerNode = (trigger = { type: 'manual' }) => ({
  id: 'trigger-root',
  type: 'triggerNode',
  data: { trigger },
});

describe('StepInspector', () => {
  test('renders nothing when node is null', () => {
    const { container } = render(<StepInspector node={null} onUpdate={() => {}} onClose={() => {}} />);
    expect(container.firstChild).toBeNull();
  });

  test('renders trigger config form for triggerNode', () => {
    render(<StepInspector node={triggerNode()} onUpdate={() => {}} onClose={() => {}} />);
    expect(screen.getByText(/builder.inspector.triggerConfig/)).toBeInTheDocument();
  });

  test('cron trigger shows the schedule input', () => {
    render(
      <StepInspector
        node={triggerNode({ type: 'cron', schedule: '0 9 * * *' })}
        onUpdate={() => {}}
        onClose={() => {}}
      />
    );
    expect(screen.getByDisplayValue('0 9 * * *')).toBeInTheDocument();
  });

  test('changing the trigger type calls onUpdate', () => {
    const onUpdate = jest.fn();
    render(<StepInspector node={triggerNode()} onUpdate={onUpdate} onClose={() => {}} />);
    const select = screen.getByRole('combobox');
    fireEvent.change(select, { target: { value: 'cron' } });
    expect(onUpdate).toHaveBeenCalledWith('trigger-root', expect.objectContaining({
      trigger: expect.objectContaining({ type: 'cron' }),
    }));
  });

  test('mcp_tool step renders tool input and params editor', () => {
    render(<StepInspector node={mcpNode()} onUpdate={() => {}} onClose={() => {}} />);
    expect(screen.getByDisplayValue('gmail.send')).toBeInTheDocument();
  });

  test('changing the step type calls onUpdate with new type', () => {
    const onUpdate = jest.fn();
    render(<StepInspector node={mcpNode()} onUpdate={onUpdate} onClose={() => {}} />);
    const selects = screen.getAllByRole('combobox');
    // First select is the type picker
    fireEvent.change(selects[0], { target: { value: 'agent' } });
    expect(onUpdate).toHaveBeenCalledWith('n1', expect.objectContaining({
      step: expect.objectContaining({ type: 'agent' }),
    }));
  });

  test('integrationStatus pill renders connected/disconnected', () => {
    const { rerender } = render(
      <StepInspector
        node={mcpNode()}
        integrationStatus={{ connected: true, name: 'Gmail' }}
        onUpdate={() => {}}
        onClose={() => {}}
      />
    );
    expect(screen.getByText(/Gmail/)).toBeInTheDocument();

    rerender(
      <StepInspector
        node={mcpNode()}
        integrationStatus={{ connected: false, name: 'Slack' }}
        onUpdate={() => {}}
        onClose={() => {}}
      />
    );
    expect(screen.getByText(/Slack/)).toBeInTheDocument();
  });

  test('condition step renders if-expression input', () => {
    const node = {
      id: 'c1',
      type: 'conditionNode',
      data: { step: { id: 'c1', type: 'condition', if: '{{x}} > 0' } },
    };
    render(<StepInspector node={node} onUpdate={() => {}} onClose={() => {}} />);
    expect(screen.getByDisplayValue('{{x}} > 0')).toBeInTheDocument();
  });
});
