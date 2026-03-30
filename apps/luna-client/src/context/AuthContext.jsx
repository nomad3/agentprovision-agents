import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { apiFetch, apiJson } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => {
    localStorage.removeItem('luna_token');
    setUser(null);
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('luna_token');
    if (!token) { setLoading(false); return; }
    apiJson('/api/v1/users/me')
      .then(setUser)
      .catch(() => logout())
      .finally(() => setLoading(false));
  }, [logout]);

  useEffect(() => {
    window.addEventListener('luna:logout', logout);
    return () => window.removeEventListener('luna:logout', logout);
  }, [logout]);

  const login = async (email, password) => {
    const body = new URLSearchParams({ username: email, password });
    console.log('[Luna] Login to:', import.meta.env.VITE_API_BASE_URL || '(relative)');
    const res = await apiFetch('/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    });
    const data = await res.json();
    if (!data.access_token) {
      throw new Error(data.detail || JSON.stringify(data));
    }
    localStorage.setItem('luna_token', data.access_token);
    const me = await apiJson('/api/v1/users/me');
    setUser(me);
    return me;
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
