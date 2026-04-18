import api from '../utils/api';

const transcribeAudio = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api.post('/media/transcribe', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 90000,
  });
};

const mediaService = {
  transcribeAudio,
};

export default mediaService;
