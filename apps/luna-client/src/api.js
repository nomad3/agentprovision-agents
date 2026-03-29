const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export async function apiFetch(path, options = {}) {
  const token = localStorage.getItem('luna_token');
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    localStorage.removeItem('luna_token');
    window.dispatchEvent(new Event('luna:logout'));
  }
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res;
}

export async function apiJson(path, options = {}) {
  const res = await apiFetch(path, options);
  return res.json();
}

export function apiStream(path, body, signal) {
  const token = localStorage.getItem('luna_token');
  return fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
}
