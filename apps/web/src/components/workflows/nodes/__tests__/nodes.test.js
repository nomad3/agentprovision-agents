import { render, screen } from '@testing-library/react';
import StepNode from '../StepNode';
import TriggerNode from '../TriggerNode';
import ConditionNode from '../ConditionNode';
import ForEachNode from '../ForEachNode';
import ParallelNode from '../ParallelNode';
import ApprovalNode from '../ApprovalNode';

// reactflow's Handle renders into a portal that depends on a parent provider.
// We don't care about the visual output here — only that the node body
// renders. Stub Handle/Position to plain DOM.
jest.mock('reactflow', () => ({
  Handle: () => null,
  Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
}));

describe('workflow node components', () => {
  test('StepNode renders mcp_tool with the tool name', () => {
    render(<StepNode data={{ step: { id: 's1', type: 'mcp_tool', tool: 'gmail.send' } }} />);
    expect(screen.getByText('s1')).toBeInTheDocument();
    expect(screen.getByText('gmail.send')).toBeInTheDocument();
  });

  test('StepNode falls back to mcp_tool config for unknown types', () => {
    render(<StepNode data={{ step: { id: 's1', type: 'made_up', tool: 'foo' } }} />);
    expect(screen.getByText('foo')).toBeInTheDocument();
  });

  test('StepNode renders the integration badge when provided', () => {
    render(
      <StepNode
        data={{
          step: { id: 's1', type: 'mcp_tool', tool: 't' },
          integrationStatus: { connected: false, name: 'Gmail' },
        }}
      />
    );
    expect(screen.getByText('Gmail')).toBeInTheDocument();
  });

  test('StepNode renders selected class when selected', () => {
    const { container } = render(
      <StepNode data={{ step: { id: 's1', type: 'mcp_tool' } }} selected />
    );
    expect(container.querySelector('.selected')).toBeInTheDocument();
  });

  test('TriggerNode shows cron schedule', () => {
    render(<TriggerNode data={{ trigger: { type: 'cron', schedule: '0 9 * * *' } }} />);
    expect(screen.getByText(/0 9/)).toBeInTheDocument();
  });

  test('TriggerNode defaults to manual when no trigger given', () => {
    render(<TriggerNode data={{}} />);
    expect(screen.getByText(/Manual trigger/)).toBeInTheDocument();
  });

  test('TriggerNode covers webhook + interval + event branches', () => {
    const { rerender } = render(<TriggerNode data={{ trigger: { type: 'webhook' } }} />);
    expect(screen.getByText(/Webhook trigger/)).toBeInTheDocument();

    rerender(<TriggerNode data={{ trigger: { type: 'interval', interval_minutes: 15 } }} />);
    expect(screen.getByText(/Every 15 min/)).toBeInTheDocument();

    rerender(<TriggerNode data={{ trigger: { type: 'event', event_type: 'gmail.received' } }} />);
    expect(screen.getByText(/On: gmail.received/)).toBeInTheDocument();
  });

  test('ConditionNode renders the if expression', () => {
    render(<ConditionNode data={{ step: { id: 'c1', if: 'x > 0' } }} />);
    expect(screen.getByText('c1')).toBeInTheDocument();
    expect(screen.getByText('x > 0')).toBeInTheDocument();
    expect(screen.getByText('Then')).toBeInTheDocument();
    expect(screen.getByText('Else')).toBeInTheDocument();
  });

  test('ConditionNode falls back to "condition" when no if expression', () => {
    render(<ConditionNode data={{ step: { id: 'c1' } }} />);
    expect(screen.getByText('condition')).toBeInTheDocument();
  });

  test('ForEachNode renders sub-step count and collection', () => {
    render(
      <ForEachNode
        data={{
          step: { id: 'fe', as: 'lead', collection: '{{leads}}', steps: [{ id: 's' }] },
        }}
      />
    );
    expect(screen.getByText(/1 sub-steps/)).toBeInTheDocument();
    expect(screen.getByText('lead')).toBeInTheDocument();
  });

  test('ParallelNode shows branch count', () => {
    render(
      <ParallelNode
        data={{ step: { id: 'p1', steps: [{ id: 'a' }, { id: 'b' }, { id: 'c' }] } }}
      />
    );
    expect(screen.getByText(/3 parallel branches/)).toBeInTheDocument();
  });

  test('ApprovalNode renders prompt and execution status', () => {
    render(
      <ApprovalNode
        data={{
          step: { id: 'a1', prompt: 'Approve deploy?' },
          executionStatus: { status: 'pending' },
        }}
      />
    );
    expect(screen.getByText('Approve deploy?')).toBeInTheDocument();
    expect(screen.getByText('pending')).toBeInTheDocument();
  });

  test('ApprovalNode falls back to default copy', () => {
    render(<ApprovalNode data={{ step: { id: 'a1' } }} />);
    expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument();
  });
});
