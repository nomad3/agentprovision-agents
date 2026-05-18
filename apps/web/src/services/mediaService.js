import api from '../utils/api';

// Polling parameters for the async transcription fallback. The api may
// return `{ status: "pending", job_id }` when the code-worker workflow
// (apps/code-worker/transcription.py) takes longer than the server-side
// sync window. We poll `GET /media/transcription/{job_id}` until the
// status flips or we exceed `MAX_POLL_MS`.
const POLL_INTERVAL_MS = 1000;
const MAX_POLL_MS = 90_000; // matches the original axios timeout

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const pollTranscription = async (jobId) => {
  const start = Date.now();
  while (Date.now() - start < MAX_POLL_MS) {
    const res = await api.get(`/media/transcription/${jobId}`);
    if (res.data && res.data.status === 'completed') {
      return res;
    }
    await sleep(POLL_INTERVAL_MS);
  }
  // Timed out — surface the most recent response shape so callers
  // render the "could not understand" branch instead of a hard error.
  return {
    data: {
      status: 'timeout',
      transcript: null,
      engine: 'unavailable',
      duration_ms: 0,
      job_id: jobId,
    },
  };
};

const transcribeAudio = async (file) => {
  const formData = new FormData();
  formData.append('file', file);
  const res = await api.post('/media/transcribe', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 90000,
  });
  // Phase A of the api image diet pushed whisper to the code-worker;
  // short clips still return inline (`status: completed`), longer clips
  // come back as `{ status: "pending", job_id }` and we poll until done.
  if (res?.data?.status === 'pending' && res?.data?.job_id) {
    return pollTranscription(res.data.job_id);
  }
  return res;
};

const mediaService = {
  transcribeAudio,
};

export default mediaService;
