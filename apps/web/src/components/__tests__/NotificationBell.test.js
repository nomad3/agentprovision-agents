import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import NotificationBell from '../NotificationBell';
import { notificationService } from '../../services/notifications';

jest.mock('../../services/notifications', () => ({
  notificationService: {
    getUnreadCount: jest.fn(),
    getNotifications: jest.fn(),
    markRead: jest.fn(),
    markAllRead: jest.fn(),
    dismiss: jest.fn(),
  },
}));

const sampleNotifications = [
  {
    id: 'n1',
    title: 'New email from Brett',
    body: 'Your billing report is ready for review.',
    source: 'gmail',
    priority: 'high',
    read: false,
    created_at: new Date().toISOString(),
  },
  {
    id: 'n2',
    title: 'Meeting at 3pm',
    body: 'Standup with the platform team.',
    source: 'calendar',
    priority: 'medium',
    read: true,
    created_at: new Date(Date.now() - 1000 * 60 * 90).toISOString(),
  },
];

describe('NotificationBell', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
    notificationService.getUnreadCount.mockResolvedValue(3);
    notificationService.getNotifications.mockResolvedValue(sampleNotifications);
    notificationService.markRead.mockResolvedValue(undefined);
    notificationService.markAllRead.mockResolvedValue(undefined);
    notificationService.dismiss.mockResolvedValue(undefined);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('renders bell and fetches unread count on mount', async () => {
    render(<NotificationBell />);
    await waitFor(() => {
      expect(notificationService.getUnreadCount).toHaveBeenCalled();
    });
    expect(await screen.findByText('3')).toBeInTheDocument();
  });

  test('shows 99+ when unread count exceeds 99', async () => {
    notificationService.getUnreadCount.mockResolvedValue(150);
    render(<NotificationBell />);
    expect(await screen.findByText('99+')).toBeInTheDocument();
  });

  test('does not render the badge when count is zero', async () => {
    notificationService.getUnreadCount.mockResolvedValue(0);
    render(<NotificationBell />);
    await waitFor(() => expect(notificationService.getUnreadCount).toHaveBeenCalled());
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  test('opens dropdown and fetches notifications', async () => {
    render(<NotificationBell />);
    const toggle = await screen.findByRole('button');
    fireEvent.click(toggle);
    await waitFor(() => {
      expect(notificationService.getNotifications).toHaveBeenCalledWith({ limit: 10 });
    });
    expect(await screen.findByText('New email from Brett')).toBeInTheDocument();
    expect(await screen.findByText('Meeting at 3pm')).toBeInTheDocument();
  });

  test('shows empty-state copy when no notifications exist', async () => {
    notificationService.getNotifications.mockResolvedValue([]);
    notificationService.getUnreadCount.mockResolvedValue(0);
    render(<NotificationBell />);
    const toggle = await screen.findByRole('button');
    fireEvent.click(toggle);
    expect(await screen.findByText(/No notifications yet/i)).toBeInTheDocument();
  });

  test('mark-all-read clears the badge and calls the service', async () => {
    render(<NotificationBell />);
    const toggle = await screen.findByRole('button');
    fireEvent.click(toggle);
    const markAll = await screen.findByText(/Mark all read/i);
    await act(async () => {
      fireEvent.click(markAll);
    });
    expect(notificationService.markAllRead).toHaveBeenCalled();
  });

  test('polls unread count on interval', async () => {
    render(<NotificationBell />);
    await waitFor(() => expect(notificationService.getUnreadCount).toHaveBeenCalledTimes(1));
    await act(async () => {
      jest.advanceTimersByTime(60000);
    });
    expect(notificationService.getUnreadCount).toHaveBeenCalledTimes(2);
  });
});
