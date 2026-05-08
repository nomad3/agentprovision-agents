import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const apiJsonMock = vi.fn();

vi.mock('../../api', () => ({
  apiJson: (...args) => apiJsonMock(...args),
}));

vi.mock('@tauri-apps/plugin-notification', () => ({
  sendNotification: vi.fn(),
  isPermissionGranted: vi.fn(() => Promise.resolve(true)),
  requestPermission: vi.fn(() => Promise.resolve('granted')),
}));

import NotificationBell from '../NotificationBell';

beforeEach(() => {
  apiJsonMock.mockReset();
});

describe('NotificationBell', () => {
  it('renders the bell button', () => {
    apiJsonMock.mockResolvedValue({ unread: 0 });
    render(<NotificationBell />);
    expect(document.querySelector('.notif-bell')).toBeInTheDocument();
  });

  it('does not show the badge when unread count is 0', async () => {
    apiJsonMock.mockResolvedValue({ unread: 0 });
    render(<NotificationBell />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/notifications/count'));
    expect(document.querySelector('.notif-badge')).not.toBeInTheDocument();
  });

  it('shows the badge with the unread count from the count endpoint', async () => {
    apiJsonMock.mockResolvedValue({ unread: 3 });
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText('3')).toBeInTheDocument());
  });

  it('caps the badge at 99+ for large counts', async () => {
    apiJsonMock.mockResolvedValue({ unread: 250 });
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText('99+')).toBeInTheDocument());
  });

  it('opens the dropdown and fetches the full list on click', async () => {
    apiJsonMock.mockResolvedValueOnce({ unread: 1 });
    apiJsonMock.mockResolvedValueOnce([
      { id: 1, source: 'gmail', title: 'New email from Brett', body: 'Cardio results attached', read: false, created_at: new Date().toISOString() },
    ]);
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText('1')).toBeInTheDocument());
    fireEvent.click(document.querySelector('.notif-bell'));
    await waitFor(() => expect(screen.getByText('New email from Brett')).toBeInTheDocument());
    expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/notifications?limit=20&unread_only=false');
  });

  it('shows the empty state when no notifications are returned', async () => {
    apiJsonMock.mockResolvedValueOnce({ unread: 0 });
    apiJsonMock.mockResolvedValueOnce([]);
    render(<NotificationBell />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalledTimes(1));
    fireEvent.click(document.querySelector('.notif-bell'));
    await waitFor(() => expect(screen.getByText(/no notifications/i)).toBeInTheDocument());
  });

  it('closes the dropdown when the close button is clicked', async () => {
    apiJsonMock.mockResolvedValueOnce({ unread: 0 });
    apiJsonMock.mockResolvedValueOnce([]);
    render(<NotificationBell />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalledTimes(1));
    fireEvent.click(document.querySelector('.notif-bell'));
    await waitFor(() => expect(document.querySelector('.notif-dropdown')).toBeInTheDocument());
    fireEvent.click(document.querySelector('.notif-close'));
    expect(screen.queryByText(/no notifications/i)).not.toBeInTheDocument();
  });

  it('toggles the dropdown open then closed by clicking the bell twice', async () => {
    apiJsonMock.mockResolvedValueOnce({ unread: 0 });
    apiJsonMock.mockResolvedValueOnce([]);
    render(<NotificationBell />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalledTimes(1));
    const bell = document.querySelector('.notif-bell');
    fireEvent.click(bell);
    await waitFor(() => expect(screen.getByText(/no notifications/i)).toBeInTheDocument());
    fireEvent.click(bell);
    expect(screen.queryByText(/no notifications/i)).not.toBeInTheDocument();
  });

  it('marks an unread notification as read when the check button is clicked', async () => {
    apiJsonMock.mockResolvedValueOnce({ unread: 2 });
    apiJsonMock.mockResolvedValueOnce([
      { id: 7, source: 'calendar', title: 'Standup', body: '', read: false, created_at: new Date().toISOString() },
      { id: 8, source: 'whatsapp', title: 'Hey', body: '', read: false, created_at: new Date().toISOString() },
    ]);
    apiJsonMock.mockResolvedValueOnce({});
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText('2')).toBeInTheDocument());
    fireEvent.click(document.querySelector('.notif-bell'));
    await waitFor(() => expect(screen.getByText('Standup')).toBeInTheDocument());
    const markBtn = document.querySelector('button[title="Mark read"]');
    expect(markBtn).toBeInTheDocument();
    fireEvent.click(markBtn);
    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/notifications/7/read', { method: 'PATCH' });
    });
    await waitFor(() => expect(screen.getByText('1')).toBeInTheDocument());
  });

  it('dismisses a notification when the X button is clicked', async () => {
    apiJsonMock.mockResolvedValueOnce({ unread: 1 });
    apiJsonMock.mockResolvedValueOnce([
      { id: 9, source: 'gmail', title: 'Will be dismissed', body: '', read: false, created_at: new Date().toISOString() },
    ]);
    apiJsonMock.mockResolvedValueOnce({});
    render(<NotificationBell />);
    await waitFor(() => expect(screen.getByText('1')).toBeInTheDocument());
    fireEvent.click(document.querySelector('.notif-bell'));
    await waitFor(() => expect(screen.getByText('Will be dismissed')).toBeInTheDocument());
    const dismissBtn = document.querySelector('button[title="Dismiss"]');
    expect(dismissBtn).toBeInTheDocument();
    fireEvent.click(dismissBtn);
    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith('/api/v1/notifications/9', { method: 'DELETE' });
    });
    await waitFor(() => expect(screen.queryByText('Will be dismissed')).not.toBeInTheDocument());
  });

  it('truncates long notification bodies to 100 chars', async () => {
    const longBody = 'x'.repeat(200);
    apiJsonMock.mockResolvedValueOnce({ unread: 0 });
    apiJsonMock.mockResolvedValueOnce([
      { id: 1, source: 'gmail', title: 'Long', body: longBody, read: true, created_at: new Date().toISOString() },
    ]);
    render(<NotificationBell />);
    await waitFor(() => expect(apiJsonMock).toHaveBeenCalledTimes(1));
    fireEvent.click(document.querySelector('.notif-bell'));
    await waitFor(() => expect(screen.getByText('Long')).toBeInTheDocument());
    // The visible body should be exactly 100 chars
    const body = document.querySelector('.notif-content p');
    expect(body.textContent.length).toBe(100);
  });
});
