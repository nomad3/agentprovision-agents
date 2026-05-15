/*
 * StatusBar — bottom strip with at-a-glance counters.
 *
 * Phase 1: shows tenant id, current session id, "kernel: alpha-cli", and
 * a placeholder for live event rate (wired in Phase 2 when we have a
 * global event subscription). Click ⌘K hint navigates nowhere yet —
 * the palette lands in Phase 2.
 */
import { useAuth } from '../App';
import './StatusBar.css';

const StatusBar = ({ sessionId }) => {
  const auth = useAuth();
  return (
    <div className="ap-statusbar">
      <div className="ap-statusbar-cell">● kernel: alpha-cli</div>
      <div className="ap-statusbar-cell">
        tenant: {auth.user?.tenant_id ? String(auth.user.tenant_id).slice(0, 8) : '—'}
      </div>
      <div className="ap-statusbar-cell">
        session: {sessionId ? String(sessionId).slice(0, 8) : '—'}
      </div>
      <div className="ap-statusbar-spacer" />
      <div className="ap-statusbar-cell ap-statusbar-hint">⌘K · search (Phase 2)</div>
    </div>
  );
};

export default StatusBar;
