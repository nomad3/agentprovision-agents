import { notificationService } from '../notifications';
import api from '../api';

jest.mock('../api');

describe('notificationService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('getNotifications builds default query string', async () => {
    api.get.mockResolvedValue({ data: [] });
    await notificationService.getNotifications();
    expect(api.get).toHaveBeenCalledWith('/notifications?skip=0&limit=20');
  });

  test('getNotifications appends unread_only when requested', async () => {
    api.get.mockResolvedValue({ data: [] });
    await notificationService.getNotifications({ unreadOnly: true, skip: 5, limit: 10 });
    expect(api.get.mock.calls[0][0]).toContain('unread_only=true');
    expect(api.get.mock.calls[0][0]).toContain('skip=5');
    expect(api.get.mock.calls[0][0]).toContain('limit=10');
  });

  test('getUnreadCount returns the unread field', async () => {
    api.get.mockResolvedValue({ data: { unread: 7 } });
    expect(await notificationService.getUnreadCount()).toBe(7);
    expect(api.get).toHaveBeenCalledWith('/notifications/count');
  });

  test('markRead PATCHes the id endpoint', async () => {
    api.patch.mockResolvedValue({ data: {} });
    await notificationService.markRead('abc');
    expect(api.patch).toHaveBeenCalledWith('/notifications/abc/read');
  });

  test('markAllRead PATCHes the bulk endpoint', async () => {
    api.patch.mockResolvedValue({ data: {} });
    await notificationService.markAllRead();
    expect(api.patch).toHaveBeenCalledWith('/notifications/read-all');
  });

  test('dismiss DELETEs the id endpoint', async () => {
    api.delete.mockResolvedValue({ data: {} });
    await notificationService.dismiss('abc');
    expect(api.delete).toHaveBeenCalledWith('/notifications/abc');
  });

  test('startInboxMonitor passes interval', async () => {
    api.post.mockResolvedValue({ data: { ok: true } });
    await notificationService.startInboxMonitor(30);
    expect(api.post).toHaveBeenCalledWith('/workflows/inbox-monitor/start?check_interval_minutes=30');
  });

  test('stopInboxMonitor + getInboxMonitorStatus call the right endpoints', async () => {
    api.post.mockResolvedValue({ data: { ok: true } });
    api.get.mockResolvedValue({ data: { running: false } });
    await notificationService.stopInboxMonitor();
    expect(api.post).toHaveBeenCalledWith('/workflows/inbox-monitor/stop');
    await notificationService.getInboxMonitorStatus();
    expect(api.get).toHaveBeenCalledWith('/workflows/inbox-monitor/status');
  });
});
