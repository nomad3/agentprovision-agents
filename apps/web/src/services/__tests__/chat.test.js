import chatService from '../chat';
import api from '../../utils/api';

jest.mock('../../utils/api');

describe('chatService (axios endpoints)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockResolvedValue({ data: [] });
    api.post.mockResolvedValue({ data: { id: 's1' } });
  });

  test('listSessions hits /chat/sessions', async () => {
    await chatService.listSessions();
    expect(api.get).toHaveBeenCalledWith('/chat/sessions');
  });

  test('createSession posts the payload', async () => {
    await chatService.createSession({ title: 'X', agent_id: 'a1' });
    expect(api.post).toHaveBeenCalledWith('/chat/sessions', { title: 'X', agent_id: 'a1' });
  });

  test('listMessages + getSessionEntities use the session id', async () => {
    await chatService.listMessages('s1');
    expect(api.get).toHaveBeenCalledWith('/chat/sessions/s1/messages');

    await chatService.getSessionEntities('s1');
    expect(api.get).toHaveBeenCalledWith('/chat/sessions/s1/entities');
  });

  test('postMessage posts the content', async () => {
    await chatService.postMessage('s1', 'hello');
    expect(api.post).toHaveBeenCalledWith('/chat/sessions/s1/messages', { content: 'hello' });
  });

  test('postMessageWithFile uses multipart/form-data', async () => {
    const file = new File(['hi'], 'a.txt', { type: 'text/plain' });
    await chatService.postMessageWithFile('s1', 'caption', file);
    expect(api.post).toHaveBeenCalledWith(
      '/chat/sessions/s1/messages/upload',
      expect.any(FormData),
      expect.objectContaining({
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000,
      })
    );
  });
});

describe('chatService.postMessageStream', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('user', JSON.stringify({ access_token: 'tok-1' }));
  });

  test('aborts and reports an error when the stream returns non-2xx', async () => {
    const fakeFetch = jest.fn(async () => ({
      ok: false,
      statusText: 'Bad Request',
      json: async () => ({ detail: 'broken' }),
    }));
    global.fetch = fakeFetch;
    const onError = jest.fn();
    chatService.postMessageStream('s1', 'hi', jest.fn(), jest.fn(), jest.fn(), onError);
    await new Promise((r) => setTimeout(r, 0));
    expect(fakeFetch).toHaveBeenCalledWith(
      '/api/v1/chat/sessions/s1/messages/stream',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer tok-1' }),
      })
    );
    expect(onError).toHaveBeenCalledWith('broken');
  });
});
