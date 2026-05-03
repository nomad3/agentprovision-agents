import channelService from '../channelService';
import api from '../api';

jest.mock('../api');

describe('channelService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockResolvedValue({ data: {} });
    api.post.mockResolvedValue({ data: {} });
    api.put.mockResolvedValue({ data: {} });
  });

  test('WhatsApp endpoints', async () => {
    await channelService.enableWhatsApp({ phone: '+5491234' });
    expect(api.post).toHaveBeenCalledWith('/channels/whatsapp/enable', { phone: '+5491234' });

    await channelService.disableWhatsApp();
    expect(api.post).toHaveBeenCalledWith('/channels/whatsapp/disable', {});

    await channelService.updateWhatsAppSettings({ auto_reply: true });
    expect(api.put).toHaveBeenCalledWith('/channels/whatsapp/settings', { auto_reply: true });

    await channelService.getWhatsAppStatus();
    expect(api.get).toHaveBeenCalledWith('/channels/whatsapp/status');

    await channelService.startPairing();
    expect(api.post).toHaveBeenCalledWith('/channels/whatsapp/pair', {});

    await channelService.getPairingStatus({ session_id: 'abc' });
    expect(api.get).toHaveBeenCalledWith('/channels/whatsapp/pair/status', { params: { session_id: 'abc' } });

    await channelService.logoutWhatsApp();
    expect(api.post).toHaveBeenCalledWith('/channels/whatsapp/logout', {});

    await channelService.sendWhatsApp({ to: '+1', message: 'hi' });
    expect(api.post).toHaveBeenCalledWith('/channels/whatsapp/send', { to: '+1', message: 'hi' });
  });
});
