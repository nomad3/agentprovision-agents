import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import LoginPage from '../LoginPage';

const mockLogin = jest.fn();
const mockNavigate = jest.fn();

jest.mock('../../App', () => ({
  useAuth: () => ({ login: mockLogin }),
}));

jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

jest.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (k) => {
      const map = {
        'login.title': 'Sign in',
        'login.email': 'Email',
        'login.emailPlaceholder': 'you@example.com',
        'login.password': 'Password',
        'login.passwordPlaceholder': '••••••••',
        'login.submit': 'Sign in',
        'login.loggingIn': 'Signing in...',
        'login.noAccount': "Don't have an account?",
        'login.registerLink': 'Register',
        'login.error': 'Invalid credentials',
      };
      return map[k] || k;
    },
  }),
}));

describe('LoginPage', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockLogin.mockReset();
    mockNavigate.mockReset();
  });
  afterEach(() => {
    jest.useRealTimers();
  });

  test('renders the form with email/password and a submit button', () => {
    render(<LoginPage />);
    expect(screen.getByText('Sign in', { selector: 'h2' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('you@example.com')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('••••••••')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Sign in/ })).toBeInTheDocument();
  });

  test('successful login navigates to /dashboard', async () => {
    jest.useRealTimers();
    mockLogin.mockResolvedValue({ access_token: 'tok' });
    render(<LoginPage />);
    fireEvent.change(screen.getByPlaceholderText('you@example.com'), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: /Sign in/ }));

    await waitFor(() => expect(mockLogin).toHaveBeenCalledWith('a@b.com', 'pw'));
    await waitFor(
      () => expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true }),
      { timeout: 1000 }
    );
  });

  test('failed login surfaces an error alert', async () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});
    mockLogin.mockRejectedValue(new Error('nope'));
    render(<LoginPage />);
    fireEvent.change(screen.getByPlaceholderText('you@example.com'), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: /Sign in/ }));

    await screen.findByText('Invalid credentials');
    expect(mockNavigate).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  test('disables the submit button while loading', async () => {
    let resolve;
    mockLogin.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<LoginPage />);
    fireEvent.change(screen.getByPlaceholderText('you@example.com'), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: /Sign in/ }));
    expect(screen.getByRole('button', { name: /Signing in/ })).toBeDisabled();
    await act(async () => {
      resolve({});
    });
  });
});
