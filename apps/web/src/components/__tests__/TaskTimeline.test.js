import { render, screen } from '@testing-library/react';
import TaskTimeline from '../TaskTimeline';

describe('TaskTimeline', () => {
  test('renders empty-state when traces is missing or empty', () => {
    const { rerender } = render(<TaskTimeline />);
    expect(screen.getByText(/No execution trace available/i)).toBeInTheDocument();

    rerender(<TaskTimeline traces={[]} />);
    expect(screen.getByText(/No execution trace available/i)).toBeInTheDocument();
  });

  test('renders one row per trace with step type as upper-cased label', () => {
    const traces = [
      { step_type: 'memory_recall', created_at: '2026-05-03T12:00:00Z' },
      { step_type: 'completed', created_at: '2026-05-03T12:00:01Z' },
    ];
    render(<TaskTimeline traces={traces} />);
    expect(screen.getByText('MEMORY RECALL')).toBeInTheDocument();
    expect(screen.getByText('COMPLETED')).toBeInTheDocument();
  });

  test('falls back to event_type when step_type is missing', () => {
    render(
      <TaskTimeline
        traces={[{ event_type: 'workflow_started', created_at: '2026-05-03T00:00:00Z' }]}
      />
    );
    expect(screen.getByText('WORKFLOW STARTED')).toBeInTheDocument();
  });

  test('renders the activity name pill when distinct from step type', () => {
    render(
      <TaskTimeline
        traces={[{ step_type: 'activity_started', activity_name: 'sendEmail' }]}
      />
    );
    expect(screen.getByText('sendEmail')).toBeInTheDocument();
  });

  test('formats short and long durations as a badge', () => {
    render(
      <TaskTimeline
        traces={[
          { step_type: 'a', duration_ms: 250 },
          { step_type: 'b', duration_ms: 1500 },
          { step_type: 'c', duration_ms: 120000 },
        ]}
      />
    );
    expect(screen.getByText('250ms')).toBeInTheDocument();
    expect(screen.getByText('1.5s')).toBeInTheDocument();
    expect(screen.getByText('2m 0s')).toBeInTheDocument();
  });

  test('formats string vs object details', () => {
    render(
      <TaskTimeline
        traces={[
          { step_type: 'a', details: 'simple string' },
          { step_type: 'b', details: { foo: 'bar' } },
        ]}
      />
    );
    expect(screen.getByText('simple string')).toBeInTheDocument();
    expect(screen.getByText(/"foo": "bar"/)).toBeInTheDocument();
  });

  test('handles unknown step types gracefully', () => {
    render(<TaskTimeline traces={[{ step_type: 'something_weird' }]} />);
    expect(screen.getByText('SOMETHING WEIRD')).toBeInTheDocument();
  });

  test('handles null/undefined step type', () => {
    render(<TaskTimeline traces={[{ details: 'no step type' }]} />);
    expect(screen.getByText('UNKNOWN')).toBeInTheDocument();
  });
});
