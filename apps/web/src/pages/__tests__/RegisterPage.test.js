import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import RegisterPage from '../RegisterPage';
import authService from '../../services/auth';

jest.mock('../../services/auth', () => ({
  __esModule: true,
  default: { register: jest.fn() },
}));

const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../__mocks__/react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k) => k }),
}));

describe('RegisterPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('submits the registration payload', async () => {
    authService.register.mockResolvedValue({ id: 'u1' });
    render(<RegisterPage />);
    fireEvent.change(screen.getByPlaceholderText('register.emailPlaceholder'), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByPlaceholderText('register.passwordPlaceholder'), { target: { value: 'pw' } });
    fireEvent.change(screen.getByPlaceholderText('register.fullNamePlaceholder'), { target: { value: 'Eve' } });
    fireEvent.change(screen.getByPlaceholderText('register.tenantNamePlaceholder'), { target: { value: 'Acme' } });
    fireEvent.click(screen.getByRole('button', { name: 'register.submit' }));

    await waitFor(() =>
      expect(authService.register).toHaveBeenCalledWith('a@b.com', 'pw', 'Eve', 'Acme')
    );
    expect(await screen.findByText('register.success')).toBeInTheDocument();
  });

  test('renders an error alert when registration fails', async () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});
    authService.register.mockRejectedValue({ response: { data: { detail: 'email taken' } } });
    render(<RegisterPage />);
    fireEvent.change(screen.getByPlaceholderText('register.emailPlaceholder'), { target: { value: 'a@b.com' } });
    fireEvent.change(screen.getByPlaceholderText('register.passwordPlaceholder'), { target: { value: 'pw' } });
    fireEvent.change(screen.getByPlaceholderText('register.fullNamePlaceholder'), { target: { value: 'Eve' } });
    fireEvent.change(screen.getByPlaceholderText('register.tenantNamePlaceholder'), { target: { value: 'Acme' } });
    fireEvent.click(screen.getByRole('button', { name: 'register.submit' }));
    expect(await screen.findByText('email taken')).toBeInTheDocument();
    spy.mockRestore();
  });
});
