// Luna Phase 5.2 — governed perception transport (client).
//
// Captures the frontmost app's window via the Rust `governed_capture_observation`
// command (secure-input + own-window + window-scope gates, all fail-closed), then
// uploads the PNG to the GOVERNED quarantine endpoint. This deliberately does NOT
// use the chat screenshot upload (`/messages/upload`), which feeds image_b64 into
// the CLI planner — P5.2 is transport-only with no planner feed. The bytes land in
// an API-only quarantine; the server returns only a byte-free reference. Nothing
// reads the bytes back in P5.2.
import { API_BASE } from '../api';

function base64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) {
    bytes[i] = bin.charCodeAt(i);
  }
  return bytes;
}

export const GOVERNED_OBSERVATION_PATH = '/api/v1/desktop-control/observations';

export async function captureAndUploadObservation({
  sessionId,
  shellId,
  deviceToken,
  invoke,
  fetchImpl = typeof fetch !== 'undefined' ? fetch : undefined,
  token = typeof localStorage !== 'undefined' ? localStorage.getItem('luna_token') : null,
  apiBase = API_BASE,
}) {
  if (!sessionId || !shellId || !deviceToken) {
    throw new Error('captureAndUploadObservation requires sessionId, shellId, deviceToken');
  }
  if (typeof fetchImpl !== 'function') {
    throw new Error('captureAndUploadObservation requires a fetch implementation');
  }

  // 1. Governed capture in Rust — fail-closed gates run there.
  const result = await invoke('governed_capture_observation');
  if (!result || !result.image_base64) {
    throw new Error('governed capture returned no image');
  }

  // 2. PNG blob from the captured bytes.
  const blob = new Blob([base64ToBytes(result.image_base64)], { type: 'image/png' });
  const form = new FormData();
  form.append('file', blob, 'observation.png');
  form.append('session_id', sessionId);
  form.append('shell_id', shellId);
  if (result.source_window_bundle_id) {
    form.append('source_window_bundle_id', result.source_window_bundle_id);
  }

  // 3. Upload to the GOVERNED quarantine endpoint (NOT the chat path). Raw
  //    multipart fetch: never set Content-Type (the browser sets the boundary);
  //    carry the JWT + the device-token proof the server binds.
  const headers = { 'X-Device-Token': deviceToken };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  const res = await fetchImpl(`${apiBase}${GOVERNED_OBSERVATION_PATH}`, {
    method: 'POST',
    headers,
    body: form,
  });
  if (!res || !res.ok) {
    throw new Error(`observation upload failed: ${res ? res.status : 'no response'}`);
  }
  return res.json();
}
