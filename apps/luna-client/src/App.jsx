import React, { useState, useCallback, useEffect } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import ChatInterface from './components/ChatInterface';
import LoginForm from './components/LoginForm';
import NotificationBell from './components/NotificationBell';
import TrustBadge from './components/TrustBadge';
import ActionApproval from './components/ActionApproval';
import CommandPalette from './components/CommandPalette';
import ClipboardToast from './components/ClipboardToast';
import { useShellPresence } from './hooks/useShellPresence';
import { useTrustProfile } from './hooks/useTrustProfile';
import { apiJson } from './api';
import './App.css';

function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('luna_theme') || 'dark');
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('luna_theme', theme);
  }, [theme]);
  const toggle = useCallback(() => setTheme(t => t === 'dark' ? 'light' : 'dark'), []);
  return { theme, toggle };
}

function useUpdateBanner() {
  const [updateVersion, setUpdateVersion] = useState(null);
  useEffect(() => {
    let unlisten;
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlisten = await listen('update-available', (event) => {
          setUpdateVersion(event.payload);
        });
      } catch {} // Not in Tauri (PWA mode)
    })();
    return () => { unlisten?.(); };
  }, []);
  const dismiss = useCallback(() => setUpdateVersion(null), []);
  const restart = useCallback(async () => {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('plugin:updater|restart');
    } catch {
      window.location.reload();
    }
  }, []);
  return { updateVersion, dismiss, restart };
}

function AuthenticatedApp() {
  const { logout } = useAuth();
  const { handoff } = useShellPresence();
  const { trust, needsConfirmation } = useTrustProfile();
  const { theme, toggle: toggleTheme } = useTheme();
  const { updateVersion, dismiss: dismissUpdate, restart: restartForUpdate } = useUpdateBanner();
  const [pendingAction, setPendingAction] = useState(null);
  const pendingResolve = React.useRef(null);
  const [paletteOpen, setPaletteOpen] = useState(false);

  // Listen for toggle-palette event from Tauri global shortcut
  useEffect(() => {
    let unlisten;
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        unlisten = await listen('toggle-palette', () => {
          setPaletteOpen(prev => !prev);
        });
      } catch {}
    })();
    return () => { unlisten?.(); };
  }, []);

  const handlePaletteSend = useCallback(async (text) => {
    try {
      // Get or create a "Luna Quick" session
      const sessions = await apiJson('/api/v1/chat/sessions');
      let sessionId;
      const quickSession = sessions.find(s => s.title === 'Luna Quick');
      if (quickSession) {
        sessionId = quickSession.id;
      } else {
        const newSession = await apiJson('/api/v1/chat/sessions', {
          method: 'POST',
          body: JSON.stringify({ title: 'Luna Quick' }),
        });
        sessionId = newSession.id;
      }
      // Send message (non-blocking — palette closes immediately)
      apiJson(`/api/v1/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content: text }),
      }).catch(() => {});
    } catch {}
  }, []);

  const requestAction = useCallback(async (action) => {
    if (!needsConfirmation) return true;
    return new Promise((resolve) => {
      pendingResolve.current = resolve;
      setPendingAction(action);
    });
  }, [needsConfirmation]);

  const handleApprove = useCallback(() => {
    pendingResolve.current?.(true);
    setPendingAction(null);
  }, []);

  const handleDeny = useCallback(() => {
    pendingResolve.current?.(false);
    setPendingAction(null);
  }, []);

  return (
    <div className="luna-app">
      <nav className="luna-nav">
        <span className="luna-brand">Luna</span>
        <div className="nav-actions">
          <button className="theme-toggle" onClick={toggleTheme} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
            {theme === 'dark' ? '\u2600' : '\u263E'}
          </button>
          <TrustBadge trust={trust} />
          <NotificationBell />
          <button className="luna-btn luna-btn-sm" onClick={logout}>Logout</button>
        </div>
      </nav>
      {updateVersion && (
        <div className="update-banner">
          <span>Luna {updateVersion} is available</span>
          <button className="luna-btn luna-btn-sm" onClick={restartForUpdate}>Restart to update</button>
          <button className="update-dismiss" onClick={dismissUpdate}>&times;</button>
        </div>
      )}
      <ChatInterface handoff={handoff} requestAction={requestAction} />
      <ActionApproval
        action={pendingAction}
        onApprove={handleApprove}
        onDeny={handleDeny}
        onDismiss={handleDeny}
      />
      <CommandPalette
        visible={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onSend={handlePaletteSend}
      />
      <ClipboardToast />
    </div>
  );
}

function AppContent() {
  const { user, loading } = useAuth();

  if (loading) return <div className="luna-loading">Loading...</div>;
  if (!user) return <LoginForm />;

  return <AuthenticatedApp />;
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
