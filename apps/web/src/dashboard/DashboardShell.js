/*
 * DashboardShell — the Alpha Control Center IDE shell.
 *
 * VSCode/Cursor-style layout:
 *   ┌────────────────── TitleBar ───────────────────┐
 *   ├──┬──────────┬──────────────────────┬─────────┤
 *   │AB│ SideBar  │     EditorArea       │  Right  │
 *   │  │          │  (multi-tab area)    │ Panel   │
 *   ├──┴──────────┴──────────────────────┴─────────┤
 *   ├──────────────── StatusBar ────────────────────┤
 *
 * Architecture: Alpha CLI is the kernel — every chat / tool / memory
 * call this UI makes lands at the API and is dispatched via
 * `cli_session_manager` to a CLI worker (claude_code / codex /
 * gemini_cli / copilot_cli). The UI is a thin viewport; no LLM call
 * is ever made directly from the browser.
 *
 * Live events render in AgentActivityPanel via the v2 SSE stream
 * (/api/v2/sessions/{id}/events), which is published by the same
 * orchestration layer that drives the CLI fleet.
 *
 * Phase 1: no terminal drawer (deferred to Phase 2).
 *
 * Tab/activity-bar state persists in localStorage so a refresh
 * doesn't lose the user's working set.
 */
import { useState } from 'react';
import ActivityBar from './ActivityBar';
import AgentActivityPanel from './AgentActivityPanel';
import EditorArea from './EditorArea';
import SideBar from './SideBar';
import StatusBar from './StatusBar';
import TitleBar from './TitleBar';
import { useTabs } from './hooks/useTabs';
import './DashboardShell.css';

const ACTIVITIES = ['chat', 'agents', 'memory', 'skills', 'workflows', 'integrations'];
const DEFAULT_ACTIVITY = 'chat';
const LS_ACTIVITY = 'apControl.activity';
// v2 key migrates past the v1 default which silently stuck users in
// collapsed mode whenever they double-clicked an icon. v1 reads are ignored.
const LS_SIDEBAR_COLLAPSED = 'apControl.sidebar.collapsed.v2';
const LS_RIGHT_COLLAPSED = 'apControl.right.collapsed';

const _readLS = (key, fallback) => {
  try {
    const v = localStorage.getItem(key);
    if (v == null) return fallback;
    return v === 'true' ? true : v === 'false' ? false : v;
  } catch {
    return fallback;
  }
};
const _writeLS = (key, value) => {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    /* swallow quota / privacy-mode errors */
  }
};

const DashboardShell = () => {
  const [activity, setActivity] = useState(() => {
    const v = _readLS(LS_ACTIVITY, DEFAULT_ACTIVITY);
    return ACTIVITIES.includes(v) ? v : DEFAULT_ACTIVITY;
  });
  // Default OPEN. Stores via the v2 key so a legitimate user-driven
  // collapse persists across refreshes; the broken v1 key is left
  // alone in localStorage but never read.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => _readLS(LS_SIDEBAR_COLLAPSED, false));
  const [rightCollapsed, setRightCollapsed] = useState(() => _readLS(LS_RIGHT_COLLAPSED, false));

  const tabsApi = useTabs();

  const handleActivity = (next) => {
    setActivity(next);
    _writeLS(LS_ACTIVITY, next);
    // If user clicks the same icon twice, toggle the sidebar collapse —
    // VSCode/Cursor parallel.
    if (next === activity) {
      const nv = !sidebarCollapsed;
      setSidebarCollapsed(nv);
      _writeLS(LS_SIDEBAR_COLLAPSED, nv);
    } else if (sidebarCollapsed) {
      setSidebarCollapsed(false);
      _writeLS(LS_SIDEBAR_COLLAPSED, false);
    }
  };

  const toggleRight = () => {
    const nv = !rightCollapsed;
    setRightCollapsed(nv);
    _writeLS(LS_RIGHT_COLLAPSED, nv);
  };

  const activeChatSessionId = tabsApi.activeTab?.kind === 'chat' ? tabsApi.activeTab.sessionId : null;

  return (
    <div
      className={`ap-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${rightCollapsed ? 'right-collapsed' : ''}`}
    >
      <TitleBar tabsApi={tabsApi} onToggleRight={toggleRight} />
      <ActivityBar active={activity} onActivate={handleActivity} />
      <SideBar activity={activity} tabsApi={tabsApi} collapsed={sidebarCollapsed} />
      <EditorArea tabsApi={tabsApi} />
      <AgentActivityPanel collapsed={rightCollapsed} sessionId={activeChatSessionId} />
      <StatusBar sessionId={activeChatSessionId} />
    </div>
  );
};

export default DashboardShell;
