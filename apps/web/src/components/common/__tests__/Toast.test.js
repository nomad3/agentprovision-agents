import { render, screen, act } from '@testing-library/react';
import { ToastProvider, useToast } from '../Toast';

const Probe = ({ onMount }) => {
  const toast = useToast();
  onMount(toast);
  return null;
};

describe('Toast', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  test('useToast outside provider throws', () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<Probe onMount={() => {}} />)).toThrow(/ToastProvider/);
    spy.mockRestore();
  });

  test('success/error/warning/info push toasts that render text', () => {
    let api;
    render(
      <ToastProvider>
        <Probe onMount={(t) => { api = t; }} />
      </ToastProvider>
    );
    act(() => {
      api.success('it worked');
    });
    expect(screen.getByText('it worked')).toBeInTheDocument();
    expect(screen.getByText('Success')).toBeInTheDocument();

    act(() => {
      api.error('it broke');
    });
    expect(screen.getByText('it broke')).toBeInTheDocument();
    expect(screen.getByText('Error')).toBeInTheDocument();
  });

  test('toast auto-dismisses after the configured duration', () => {
    let api;
    render(
      <ToastProvider>
        <Probe onMount={(t) => { api = t; }} />
      </ToastProvider>
    );
    act(() => {
      api.info('hello', 1000);
    });
    expect(screen.getByText('hello')).toBeInTheDocument();
    act(() => {
      jest.advanceTimersByTime(1000);
    });
    expect(screen.queryByText('hello')).not.toBeInTheDocument();
  });

  test('duration=0 disables auto-dismiss', () => {
    let api;
    render(
      <ToastProvider>
        <Probe onMount={(t) => { api = t; }} />
      </ToastProvider>
    );
    act(() => {
      api.warning('persistent', 0);
    });
    act(() => {
      jest.advanceTimersByTime(60000);
    });
    expect(screen.getByText('persistent')).toBeInTheDocument();
  });
});
