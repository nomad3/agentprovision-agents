import { describe, it, expect, vi } from 'vitest';
import {
  captureAndUploadObservation,
  GOVERNED_OBSERVATION_PATH,
} from '../governedObservation';

const ARGS = {
  sessionId: 'sess-1',
  shellId: 'desktop-abc',
  deviceToken: 'dev-token',
  token: 'jwt-123',
  apiBase: 'https://api.test',
};

function okJson(body) {
  return { ok: true, status: 201, json: () => Promise.resolve(body) };
}

describe('captureAndUploadObservation', () => {
  it('captures via Rust then uploads to the GOVERNED endpoint (never the chat path)', async () => {
    const invoke = vi.fn().mockResolvedValue({
      image_base64: btoa('\x89PNG\r\n\x1a\nfake'),
      source_window_bundle_id: 'com.apple.TextEdit',
    });
    const fetchImpl = vi.fn().mockResolvedValue(okJson({ artifact_id: 'a1', expires_at: 'soon' }));

    const out = await captureAndUploadObservation({ ...ARGS, invoke, fetchImpl });

    expect(invoke).toHaveBeenCalledWith('governed_capture_observation');
    // posted to the governed quarantine endpoint, not /messages/upload
    const [url, opts] = fetchImpl.mock.calls[0];
    expect(url).toBe(`https://api.test${GOVERNED_OBSERVATION_PATH}`);
    expect(url).not.toContain('/messages/upload');
    expect(url).not.toContain('/chat/');
    expect(opts.method).toBe('POST');
    // multipart: must NOT force a JSON content-type (browser sets the boundary)
    expect(opts.headers['Content-Type']).toBeUndefined();
    expect(opts.headers['X-Device-Token']).toBe('dev-token');
    expect(opts.headers.Authorization).toBe('Bearer jwt-123');
    // the form carries the governed fields
    const form = opts.body;
    expect(form.get('session_id')).toBe('sess-1');
    expect(form.get('shell_id')).toBe('desktop-abc');
    expect(form.get('source_window_bundle_id')).toBe('com.apple.TextEdit');
    expect(form.get('file')).toBeInstanceOf(Blob);
    expect(out.artifact_id).toBe('a1');
  });

  it('rejects missing required args before any capture', async () => {
    const invoke = vi.fn();
    await expect(
      captureAndUploadObservation({ ...ARGS, sessionId: null, invoke, fetchImpl: vi.fn() }),
    ).rejects.toThrow(/requires/);
    expect(invoke).not.toHaveBeenCalled();
  });

  it('throws when the upload fails (non-ok)', async () => {
    const invoke = vi.fn().mockResolvedValue({ image_base64: btoa('\x89PNG\r\n\x1a\nx') });
    const fetchImpl = vi.fn().mockResolvedValue({ ok: false, status: 403, json: () => ({}) });
    await expect(
      captureAndUploadObservation({ ...ARGS, invoke, fetchImpl }),
    ).rejects.toThrow(/403/);
  });
});
