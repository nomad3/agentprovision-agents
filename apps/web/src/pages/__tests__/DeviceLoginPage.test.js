import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import axios from 'axios';

import DeviceLoginPage from '../DeviceLoginPage';

// Stub the App.js useAuth context — the page reads `user.email` for
// the display, doesn't drive any auth behaviour itself.
jest.mock('../../App', () => ({
  useAuth: () => ({ user: { email: 'saguilera@example.test' } }),
}));

// BrandMark is a presentational SVG; stub it so we don't pull theme deps.
jest.mock('../../components/BrandMark', () => () => null);

// i18n: codebase pattern (see IntegrationsPage.test.js) — return the
// default value (second arg to t) when present, else the key. Lets the
// page render with real English copy in the test snapshot.
jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, defaultOrOpts, opts) => {
      // Variants this page uses:
      //   t(key, 'default')
      //   t(key, 'default with {{var}}', { var: 'x' })
      let value;
      if (typeof defaultOrOpts === 'string') {
        value = defaultOrOpts;
      } else {
        return key;
      }
      const interpolate = opts || (typeof defaultOrOpts === 'object' ? defaultOrOpts : null);
      if (interpolate && typeof value === 'string') {
        return value.replace(/\{\{(\w+)\}\}/g, (_, k) => interpolate[k] ?? `{{${k}}}`);
      }
      return value;
    },
  }),
}));

// useSearchParams: codebase pattern (see IntegrationsPage.test.js) —
// MemoryRouter's `initialEntries` with a `?query` doesn't reliably
// surface through useSearchParams in this jest+CRA setup; mocking the
// hook directly keeps the page-under-test focused on its own logic.
let mockCurrentSearchParams = new URLSearchParams();
const mockSetSearchParams = jest.fn();
jest.mock('react-router-dom', () => {
  // Codebase pattern: the auto-mock at src/__mocks__/react-router-dom.js
  // replaces the real module (CRA/jest moduleDirectories doesn't resolve
  // "react-router-dom" from inside the mock factory). Pull the manual
  // stub and layer useSearchParams on top.
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  return {
    ...actual,
    useSearchParams: () => [mockCurrentSearchParams, mockSetSearchParams],
  };
});

jest.mock('axios');

const renderWithSearch = (search) => {
  mockCurrentSearchParams = new URLSearchParams(search);
  return render(
    <MemoryRouter>
      <DeviceLoginPage />
    </MemoryRouter>,
  );
};

beforeEach(() => {
  jest.clearAllMocks();
});

test('renders the user_code from the query string', () => {
  renderWithSearch('user_code=5ZEU-G55U');
  expect(screen.getByTestId('device-user-code')).toHaveTextContent('5ZEU-G55U');
});

test('normalises lowercase/dashless query into canonical XXXX-XXXX', () => {
  // Server is permissive about format but the UI should display the
  // canonical form so the user can verify a match with their terminal
  // at a glance.
  renderWithSearch('user_code=5zeug55u');
  expect(screen.getByTestId('device-user-code')).toHaveTextContent('5ZEU-G55U');
});

test('shows error and does NOT POST when user_code is missing', async () => {
  renderWithSearch('');
  await waitFor(() => expect(screen.getByTestId('device-error')).toBeInTheDocument());
  expect(screen.getByTestId('device-error')).toHaveTextContent(/no user_code/i);
  expect(axios.post).not.toHaveBeenCalled();
});

test('shows error and does NOT POST when user_code is malformed', async () => {
  renderWithSearch('user_code=junk');
  await waitFor(() => expect(screen.getByTestId('device-error')).toBeInTheDocument());
  expect(screen.getByTestId('device-error')).toHaveTextContent(/XXXX-XXXX/);
  expect(axios.post).not.toHaveBeenCalled();
});

test('POSTs the canonical code to /api/v1/auth/device-approve on Approve', async () => {
  axios.post.mockResolvedValueOnce({ data: { approved: true } });
  renderWithSearch('user_code=5ZEU-G55U');
  fireEvent.click(screen.getByRole('button', { name: /approve sign-in/i }));
  await waitFor(() => expect(axios.post).toHaveBeenCalled());
  expect(axios.post).toHaveBeenCalledWith(
    '/api/v1/auth/device-approve',
    { user_code: '5ZEU-G55U' },
  );
  // Success state visible after the POST resolves.
  await waitFor(() => expect(screen.getByText(/return to your terminal/i)).toBeInTheDocument());
});

test('maps 404 to "code expired / not found" actionable copy', async () => {
  axios.post.mockRejectedValueOnce({ response: { status: 404, data: { detail: 'user_code not found or expired' } } });
  renderWithSearch('user_code=5ZEU-G55U');
  fireEvent.click(screen.getByRole('button', { name: /approve sign-in/i }));
  await waitFor(() => expect(screen.getByTestId('device-error')).toBeInTheDocument());
  expect(screen.getByTestId('device-error')).toHaveTextContent(/expired|never issued/i);
  // The actionable hint to re-run `alpha login` from the terminal is
  // the load-bearing UX — without it, the user has no idea what to do.
  expect(screen.getByTestId('device-error')).toHaveTextContent(/alpha login/i);
});

test('maps 409 to "already approved" actionable copy', async () => {
  axios.post.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'device_code already approved' } } });
  renderWithSearch('user_code=5ZEU-G55U');
  fireEvent.click(screen.getByRole('button', { name: /approve sign-in/i }));
  await waitFor(() => expect(screen.getByTestId('device-error')).toBeInTheDocument());
  expect(screen.getByTestId('device-error')).toHaveTextContent(/already approved/i);
});
