import { render, act } from '@testing-library/react';
import { useInView } from '../useInView';

// IntersectionObserver isn't in jsdom — install a controllable mock for each test.
function installIO() {
  const handle = { last: null };
  global.IntersectionObserver = function (cb, opts) {
    this.cb = cb;
    this.opts = opts;
    this.observe = jest.fn();
    this.unobserve = jest.fn();
    this.disconnect = jest.fn();
    this.trigger = (entries) => cb(entries);
    handle.last = this;
  };
  return handle;
}

const Probe = ({ options }) => {
  const [ref, isInView] = useInView(options);
  return (
    <div>
      <span ref={ref}>target</span>
      <span data-testid="state">{String(isInView)}</span>
    </div>
  );
};

describe('useInView', () => {
  let io;
  beforeEach(() => {
    io = installIO();
  });

  test('starts as not-in-view and registers the observer', () => {
    const { getByTestId } = render(<Probe />);
    expect(getByTestId('state').textContent).toBe('false');
    expect(io.last.observe).toHaveBeenCalled();
  });

  test('flips to true on intersection and stops observing', () => {
    const { getByTestId } = render(<Probe />);
    const firstObserver = io.last;
    act(() => {
      firstObserver.trigger([{ isIntersecting: true, target: {} }]);
    });
    expect(getByTestId('state').textContent).toBe('true');
    expect(firstObserver.unobserve).toHaveBeenCalled();
  });

  test('non-intersecting events do not flip the state', () => {
    const { getByTestId } = render(<Probe />);
    act(() => {
      io.last.trigger([{ isIntersecting: false, target: {} }]);
    });
    expect(getByTestId('state').textContent).toBe('false');
  });
});
