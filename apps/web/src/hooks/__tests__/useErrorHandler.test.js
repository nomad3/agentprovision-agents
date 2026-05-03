import { renderHook, act } from '@testing-library/react';
import useErrorHandler from '../useErrorHandler';

describe('useErrorHandler', () => {
  // Silence the explicit console.error inside the hook for tidy test output.
  let originalError;
  beforeAll(() => {
    originalError = console.error;
    console.error = jest.fn();
  });
  afterAll(() => {
    console.error = originalError;
  });

  test('starts with no error and not retrying', () => {
    const { result } = renderHook(() => useErrorHandler());
    expect(result.current.error).toBeNull();
    expect(result.current.isRetrying).toBe(false);
  });

  test('handleError maps known statuses to friendly copy', () => {
    const { result } = renderHook(() => useErrorHandler());
    act(() => {
      result.current.handleError({ response: { status: 401 } }, '');
    });
    expect(result.current.error.message).toMatch(/not authorized/i);
    expect(result.current.error.statusCode).toBe(401);
    expect(result.current.error.isRetryable).toBe(false);
  });

  test('5xx and 429 are flagged as retryable', () => {
    const { result } = renderHook(() => useErrorHandler());
    act(() => result.current.handleError({ response: { status: 503 } }, ''));
    expect(result.current.error.isRetryable).toBe(true);

    act(() => result.current.handleError({ response: { status: 429 } }, ''));
    expect(result.current.error.isRetryable).toBe(true);
  });

  test('messages without a response are network errors and retryable', () => {
    const { result } = renderHook(() => useErrorHandler());
    act(() => result.current.handleError({ message: 'ECONNREFUSED' }, ''));
    expect(result.current.error.message).toContain('ECONNREFUSED');
    expect(result.current.error.isRetryable).toBe(true);
  });

  test('context is prepended to the error message', () => {
    const { result } = renderHook(() => useErrorHandler());
    act(() => result.current.handleError({ response: { status: 404 } }, 'Loading agents'));
    expect(result.current.error.message).toMatch(/^Loading agents:/);
  });

  test('clearError resets the error state', () => {
    const { result } = renderHook(() => useErrorHandler());
    act(() => result.current.handleError({ response: { status: 500 } }, ''));
    expect(result.current.error).not.toBeNull();
    act(() => result.current.clearError());
    expect(result.current.error).toBeNull();
  });

  test('retry calls the function and clears the prior error on success', async () => {
    const { result } = renderHook(() => useErrorHandler());
    act(() => result.current.handleError({ response: { status: 500 } }, ''));
    const fn = jest.fn().mockResolvedValue('ok');
    await act(async () => {
      await result.current.retry(fn);
    });
    expect(fn).toHaveBeenCalled();
    expect(result.current.error).toBeNull();
    expect(result.current.isRetrying).toBe(false);
  });

  test('retry sets a fresh error if the retried function throws', async () => {
    const { result } = renderHook(() => useErrorHandler());
    const fn = jest.fn().mockRejectedValue({ response: { status: 500 } });
    await act(async () => {
      await result.current.retry(fn);
    });
    expect(result.current.error).not.toBeNull();
    expect(result.current.error.message).toMatch(/Retry failed/);
  });

  test('retry no-ops on a missing function', async () => {
    const { result } = renderHook(() => useErrorHandler());
    await act(async () => {
      await result.current.retry();
    });
    expect(result.current.error).toBeNull();
  });
});
