/*
 * FileTreePanel — left-panel Files mode for the dashboard.
 *
 * Recursive `<details>`-based tree of the user's workspace. Two scopes
 * are exposed via the toggle at the top:
 *   - `tenant`   — the user's per-tenant workspace
 *                  (/var/agentprovision/workspaces/<tenant_id>/)
 *   - `platform` — the repo's docs/plans tree, super-admin only
 *
 * Children are lazy-loaded the first time a folder is expanded. The
 * server returns directories first then files (alpha within each),
 * which we preserve. Hidden files (`.git`, `__pycache__`, dot-files)
 * are filtered server-side — we just render what we get.
 *
 * Clicking a file calls `onSelect({ path, scope })`. The host page is
 * responsible for opening a viewer (see FileViewer).
 */
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../App';
import api from '../services/api';
import './FileTreePanel.css';

const TreeNode = ({ entry, parentPath, scope, onSelect, depth }) => {
  const fullPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;

  // Folder: lazy-load on first expand. `loaded` flips after the first
  // successful fetch; the <details> can be closed/reopened without
  // refetching. If the fetch fails we surface a small inline message
  // and let the user retry by collapsing+expanding.
  const [children, setChildren] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const loadChildren = useCallback(async () => {
    if (children !== null || loading) return;
    setLoading(true);
    setErr(null);
    try {
      const resp = await api.get('/workspace/tree', {
        params: { scope, path: fullPath },
      });
      setChildren(resp.data?.entries || []);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn('tree fetch failed:', fullPath, e);
      setErr(e.response?.data?.detail || 'failed to load');
      setChildren([]);
    } finally {
      setLoading(false);
    }
  }, [scope, fullPath, children, loading]);

  if (entry.kind === 'file') {
    return (
      <button
        type="button"
        className="ftp-node ftp-file"
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={() => onSelect({ path: fullPath, scope })}
        title={fullPath}
      >
        <span className="ftp-icon" aria-hidden>•</span>
        <span className="ftp-name">{entry.name}</span>
      </button>
    );
  }

  return (
    <details
      className="ftp-dir"
      onToggle={(e) => { if (e.target.open) loadChildren(); }}
    >
      <summary
        className="ftp-node"
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
      >
        <span className="ftp-icon" aria-hidden>▸</span>
        <span className="ftp-name">{entry.name}</span>
      </summary>
      <div className="ftp-children">
        {loading && <div className="ftp-status">Loading…</div>}
        {err && <div className="ftp-status ftp-err">{err}</div>}
        {!loading && !err && children !== null && children.length === 0 && (
          <div className="ftp-status ftp-muted">empty</div>
        )}
        {children && children.map((child) => (
          <TreeNode
            key={`${fullPath}/${child.name}`}
            entry={child}
            parentPath={fullPath}
            scope={scope}
            onSelect={onSelect}
            depth={depth + 1}
          />
        ))}
      </div>
    </details>
  );
};

const FileTreePanel = ({ onSelect }) => {
  const auth = useAuth();
  const isSuperuser = !!auth?.user?.is_superuser;

  const [scope, setScope] = useState(() => {
    try {
      const v = localStorage.getItem('apControl.fileScope');
      if (v === 'platform' || v === 'tenant') return v;
    } catch { /* ignore */ }
    return 'tenant';
  });

  // Root-level entries for the current scope. Re-fetched whenever the
  // scope toggle flips.
  const [rootEntries, setRootEntries] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  // If the user is not a superuser and `platform` is somehow stuck in
  // localStorage, snap back to tenant. Defence in depth — the backend
  // returns 403 either way.
  useEffect(() => {
    if (scope === 'platform' && !isSuperuser) {
      setScope('tenant');
    }
  }, [scope, isSuperuser]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setErr(null);
      setRootEntries(null);
      try {
        const resp = await api.get('/workspace/tree', {
          params: { scope, path: '' },
        });
        if (cancelled) return;
        setRootEntries(resp.data?.entries || []);
      } catch (e) {
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.warn('root tree fetch failed:', scope, e);
        setErr(e.response?.data?.detail || 'failed to load workspace');
        setRootEntries([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [scope]);

  const handleScopeChange = (next) => {
    if (next === scope) return;
    if (next === 'platform' && !isSuperuser) return;
    setScope(next);
    try { localStorage.setItem('apControl.fileScope', next); } catch { /* quota */ }
  };

  return (
    <div className="ftp-root">
      <div className="ftp-scope-toggle" role="tablist" aria-label="File scope">
        <button
          type="button"
          role="tab"
          aria-selected={scope === 'tenant'}
          className={`ftp-scope-pill${scope === 'tenant' ? ' active' : ''}`}
          onClick={() => handleScopeChange('tenant')}
        >
          Tenant
        </button>
        {isSuperuser && (
          <button
            type="button"
            role="tab"
            aria-selected={scope === 'platform'}
            className={`ftp-scope-pill${scope === 'platform' ? ' active' : ''}`}
            onClick={() => handleScopeChange('platform')}
            title="Platform docs (super-admin only)"
          >
            Platform
          </button>
        )}
      </div>

      <div className="ftp-tree">
        {loading && <div className="ftp-status">Loading workspace…</div>}
        {err && <div className="ftp-status ftp-err">{err}</div>}
        {!loading && !err && rootEntries && rootEntries.length === 0 && (
          <div className="ftp-status ftp-muted">This workspace is empty.</div>
        )}
        {rootEntries && rootEntries.map((entry) => (
          <TreeNode
            key={entry.name}
            entry={entry}
            parentPath=""
            scope={scope}
            onSelect={onSelect}
            depth={0}
          />
        ))}
      </div>
    </div>
  );
};

export default FileTreePanel;
