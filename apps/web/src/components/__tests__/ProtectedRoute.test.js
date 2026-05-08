import { render, screen, act } from '@testing-library/react';
import ProtectedRoute from '../ProtectedRoute';

jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  const navigateLog = [];
  return {
    ...actual,
    Navigate: (props) => {
      navigateLog.push(props);
      return <div data-testid="navigate" data-to={props.to} />;
    },
    __navigateLog: navigateLog,
  };
});

jest.mock('../../App', () => {
  const state = { authValue: { user: null } };
  return {
    __esModule: true,
    useAuth: () => state.authValue,
    __setAuth: (v) => { state.authValue = v; },
  };
});

jest.mock('../common/LoadingSpinner', () => ({ text }) => (
  <div data-testid="loading-spinner">{text}</div>
));

const { __setAuth } = require('../../App');
const routerMock = require('react-router-dom');

describe('ProtectedRoute', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    routerMock.__navigateLog.length = 0;
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('renders the loading spinner during the auth check', () => {
    __setAuth({ user: { id: 'u-1' } });
    render(
      <ProtectedRoute>
        <div data-testid="child" />
      </ProtectedRoute>,
    );
    expect(screen.getByTestId('loading-spinner')).toBeInTheDocument();
  });

  test('renders children when the user is authenticated', () => {
    __setAuth({ user: { id: 'u-1' } });
    render(
      <ProtectedRoute>
        <div data-testid="child" />
      </ProtectedRoute>,
    );
    act(() => jest.advanceTimersByTime(150));
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });

  test('navigates to /login when no user is present', () => {
    __setAuth({ user: null });
    render(
      <ProtectedRoute>
        <div data-testid="child" />
      </ProtectedRoute>,
    );
    act(() => jest.advanceTimersByTime(150));
    expect(routerMock.__navigateLog.length).toBeGreaterThan(0);
    expect(routerMock.__navigateLog[0]).toMatchObject({ to: '/login', replace: true });
  });
});
