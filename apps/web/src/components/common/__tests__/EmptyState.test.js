import { render, screen } from '@testing-library/react';
import EmptyState from '../EmptyState';

const SvgIcon = (props) => <svg data-testid="icon" {...props} />;

describe('EmptyState', () => {
  test('renders title and description', () => {
    render(<EmptyState title="No agents" description="Create one to get started" />);
    expect(screen.getByText('No agents')).toBeInTheDocument();
    expect(screen.getByText('Create one to get started')).toBeInTheDocument();
  });

  test('renders icon when provided', () => {
    render(<EmptyState title="t" icon={SvgIcon} />);
    expect(screen.getByTestId('icon')).toBeInTheDocument();
  });

  test('renders action slot', () => {
    render(<EmptyState title="t" action={<button>Create</button>} />);
    expect(screen.getByRole('button', { name: 'Create' })).toBeInTheDocument();
  });

  test('omits description when not given', () => {
    const { container } = render(<EmptyState title="t" />);
    expect(container.querySelector('.empty-state-description')).toBeNull();
  });

  test('applies the variant class', () => {
    const { container } = render(<EmptyState title="t" variant="muted" />);
    expect(container.querySelector('.empty-state-muted')).toBeInTheDocument();
  });
});
