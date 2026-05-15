/*
 * useTabs — EditorArea tab state, persisted in localStorage so a refresh
 * doesn't lose the user's working set.
 *
 * Tab shape: { id: string, kind: 'chat'|'agent'|'memory'|'skill'|'workflow',
 *              title: string, ...kind-specific fields }
 *
 * Tab IDs are derived from kind + entity id so opening the same entity
 * twice focuses the existing tab instead of opening a duplicate.
 */
import { useCallback, useEffect, useState } from 'react';

const LS_TABS = 'apControl.tabs';
const LS_ACTIVE = 'apControl.activeTab';
const MAX_TABS = 20; // keep persistence bounded

const _loadTabs = () => {
  try {
    const raw = localStorage.getItem(LS_TABS);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.slice(0, MAX_TABS) : [];
  } catch {
    return [];
  }
};
const _saveTabs = (tabs) => {
  try { localStorage.setItem(LS_TABS, JSON.stringify(tabs.slice(0, MAX_TABS))); } catch { /* quota */ }
};
const _loadActive = () => {
  try { return localStorage.getItem(LS_ACTIVE) || null; } catch { return null; }
};
const _saveActive = (id) => {
  try { if (id == null) localStorage.removeItem(LS_ACTIVE); else localStorage.setItem(LS_ACTIVE, id); } catch { /* quota */ }
};

export const tabIdFor = (kind, entityId) => `${kind}:${entityId}`;

export const useTabs = () => {
  const [tabs, setTabs] = useState(_loadTabs);
  const [activeId, setActiveId] = useState(_loadActive);

  useEffect(() => { _saveTabs(tabs); }, [tabs]);
  useEffect(() => { _saveActive(activeId); }, [activeId]);

  const openTab = useCallback((tab) => {
    setTabs((prev) => {
      const idx = prev.findIndex((t) => t.id === tab.id);
      if (idx >= 0) return prev;
      const next = [...prev, tab];
      return next.length > MAX_TABS ? next.slice(next.length - MAX_TABS) : next;
    });
    setActiveId(tab.id);
  }, []);

  const closeTab = useCallback((tabId) => {
    setTabs((prev) => {
      const idx = prev.findIndex((t) => t.id === tabId);
      if (idx < 0) return prev;
      const next = prev.filter((t) => t.id !== tabId);
      if (activeId === tabId) {
        const fallback = next[idx] || next[idx - 1] || null;
        setActiveId(fallback ? fallback.id : null);
      }
      return next;
    });
  }, [activeId]);

  const activateTab = useCallback((tabId) => setActiveId(tabId), []);

  const activeTab = tabs.find((t) => t.id === activeId) || null;

  return { tabs, activeTab, activeId, openTab, closeTab, activateTab };
};
