import axios from 'axios';
import authService from '../auth';

// axios is auto-mocked from src/__mocks__/axios.js — each test resets behavior.

describe('authService', () => {
  beforeEach(() => {
    localStorage.clear();
    axios.post.mockReset();
    axios.post.mockResolvedValue({ data: {} });
  });

  test('login posts URL-encoded credentials and stores the user on success', async () => {
    axios.post.mockResolvedValue({
      data: { access_token: 'tok-123', token_type: 'bearer' },
    });
    const result = await authService.login('test@example.com', 'pw');
    expect(axios.post).toHaveBeenCalledWith(
      '/api/v1/auth/login',
      expect.any(URLSearchParams),
      expect.objectContaining({
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      })
    );
    const body = axios.post.mock.calls[0][1];
    expect(body.get('username')).toBe('test@example.com');
    expect(body.get('password')).toBe('pw');
    expect(localStorage.getItem('user')).toBe(JSON.stringify(result));
    expect(result.access_token).toBe('tok-123');
  });

  test('login does not persist when no access_token is returned', async () => {
    axios.post.mockResolvedValue({ data: { error: 'nope' } });
    await authService.login('u', 'p');
    expect(localStorage.getItem('user')).toBeNull();
  });

  test('register posts the nested user_in/tenant_in payload', async () => {
    axios.post.mockResolvedValue({ data: { id: 't1' } });
    await authService.register('e@x.com', 'pw', 'Eve', 'Acme');
    expect(axios.post).toHaveBeenCalledWith('/api/v1/auth/register', {
      user_in: { email: 'e@x.com', password: 'pw', full_name: 'Eve' },
      tenant_in: { name: 'Acme' },
    });
  });

  test('logout clears the persisted user', () => {
    localStorage.setItem('user', JSON.stringify({ access_token: 'x' }));
    authService.logout();
    expect(localStorage.getItem('user')).toBeNull();
  });

  test('getCurrentUser returns the parsed user', () => {
    localStorage.setItem('user', JSON.stringify({ id: 'u1' }));
    expect(authService.getCurrentUser()).toEqual({ id: 'u1' });
  });

  test('getCurrentUser returns null when nothing is stored', () => {
    expect(authService.getCurrentUser()).toBeNull();
  });

  test('requestPasswordReset posts the email', async () => {
    await authService.requestPasswordReset('foo@bar.com');
    expect(axios.post).toHaveBeenCalledWith('/api/v1/auth/password-reset', { email: 'foo@bar.com' });
  });

  test('resetPassword posts the token confirmation payload', async () => {
    await authService.resetPassword('foo@bar.com', 'tok', 'newpw');
    expect(axios.post).toHaveBeenCalledWith('/api/v1/auth/password-reset/confirm', {
      email: 'foo@bar.com',
      token: 'tok',
      new_password: 'newpw',
    });
  });
});
