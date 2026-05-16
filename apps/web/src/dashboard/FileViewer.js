/*
 * FileViewer — read-only file preview pane for the dashboard's Files
 * mode. Pairs with FileTreePanel: parent passes `file = {path, scope}`
 * and we fetch + render the content.
 *
 * Rendering rules:
 *   - `.md` → react-markdown (already in deps)
 *   - everything else → <pre> (whitespace-preserved, no highlighting)
 *   - binary files → placeholder; no decode attempt
 *
 * v1 is read-only. Editing / syntax highlighting / drag-drop are
 * follow-up tickets per the task scope.
 */
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import api from '../services/api';
import './FileViewer.css';

const FileViewer = ({ file }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!file?.path) {
      setData(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setErr(null);
    (async () => {
      try {
        const resp = await api.get('/workspace/file', {
          params: { scope: file.scope, path: file.path },
        });
        if (cancelled) return;
        setData(resp.data);
      } catch (e) {
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.warn('file fetch failed:', file, e);
        setErr(e.response?.data?.detail || 'failed to load file');
        setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // We intentionally watch only path+scope (the data we fetch on),
    // not the `file` reference identity which churns even when those
    // values are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file?.path, file?.scope]);

  if (!file?.path) {
    return (
      <div className="fv-empty">
        Pick a file from the tree to preview it here.
      </div>
    );
  }

  const isMarkdown = file.path.toLowerCase().endsWith('.md');

  return (
    <div className="fv-root">
      <header className="fv-header">
        <span className="fv-scope">{file.scope}</span>
        <span className="fv-path" title={file.path}>{file.path}</span>
        {data?.truncated && (
          <span className="fv-flag" title="File exceeds 256 KiB cap; only first 256 KiB shown.">
            truncated
          </span>
        )}
      </header>

      <div className="fv-body">
        {loading && <div className="fv-status">Loading…</div>}
        {err && <div className="fv-status fv-err">{err}</div>}
        {data?.is_binary && (
          <div className="fv-status fv-muted">
            Binary file ({data.size} bytes) — preview not available.
          </div>
        )}
        {!loading && !err && data && !data.is_binary && (
          isMarkdown ? (
            <div className="fv-markdown">
              <ReactMarkdown>{data.content || ''}</ReactMarkdown>
            </div>
          ) : (
            <pre className="fv-pre">{data.content || ''}</pre>
          )
        )}
      </div>
    </div>
  );
};

export default FileViewer;
