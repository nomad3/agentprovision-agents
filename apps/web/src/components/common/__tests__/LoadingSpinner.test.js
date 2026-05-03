import { render, screen } from '@testing-library/react';
import LoadingSpinner, { SkeletonLoader } from '../LoadingSpinner';

describe('LoadingSpinner', () => {
  test('renders without text by default', () => {
    const { container } = render(<LoadingSpinner />);
    expect(container.querySelector('.loading-spinner-animated')).toBeInTheDocument();
    expect(container.querySelector('.loading-spinner-text')).toBeNull();
  });

  test('renders text when provided', () => {
    render(<LoadingSpinner text="Loading agents..." />);
    expect(screen.getByText('Loading agents...')).toBeInTheDocument();
  });

  test('applies fullScreen modifier when requested', () => {
    const { container } = render(<LoadingSpinner fullScreen text="x" />);
    expect(container.querySelector('.loading-fullscreen')).toBeInTheDocument();
  });
});

describe('SkeletonLoader', () => {
  test('renders the requested number of rows', () => {
    const { container } = render(<SkeletonLoader rows={5} />);
    expect(container.querySelectorAll('.skeleton-item')).toHaveLength(5);
  });

  test('applies the height per item', () => {
    const { container } = render(<SkeletonLoader rows={1} height={100} />);
    expect(container.querySelector('.skeleton-item').style.height).toBe('100px');
  });
});
