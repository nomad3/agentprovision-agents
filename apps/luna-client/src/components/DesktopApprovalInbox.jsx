import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { apiJson } from '../api';

const DEFAULT_POLL_MS = 10000;
const APPROVAL_EXPIRES_SECONDS = 60;

function requestUrl(sessionId) {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
  return `/api/v1/desktop-control/grants/requests${query}`;
}

function labelForStatus(status) {
  switch (status) {
    case 'pending':
      return 'Pending';
    case 'approved':
      return 'Approved';
    case 'denied':
      return 'Denied';
    case 'expired':
      return 'Expired';
    default:
      return status || 'Unknown';
  }
}

function compactId(id) {
  if (!id || typeof id !== 'string') return '';
  return id.length > 12 ? `${id.slice(0, 8)}...${id.slice(-4)}` : id;
}

function expiresLabel(expiresAt) {
  if (!expiresAt) return '';
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (!Number.isFinite(ms) || ms <= 0) return 'expires now';
  const seconds = Math.ceil(ms / 1000);
  if (seconds < 90) return `expires in ${seconds}s`;
  return `expires in ${Math.ceil(seconds / 60)}m`;
}

function targetLabel(request) {
  return request?.target_bundle_id || 'unknown target';
}

export default function DesktopApprovalInbox({
  sessionId,
  pollMs = DEFAULT_POLL_MS,
}) {
  const [open, setOpen] = useState(false);
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState('');

  const hasSession = Boolean(sessionId);
  const pendingCount = requests.length;

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setRequests([]);
      setError('');
      setLoading(false);
      return;
    }
    setError('');
    setLoading(true);
    try {
      const data = await apiJson(requestUrl(sessionId));
      setRequests(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err?.message || 'Approval requests unavailable');
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!pollMs) return undefined;
    const id = window.setInterval(refresh, pollMs);
    return () => window.clearInterval(id);
  }, [pollMs, refresh]);

  const toggle = useCallback(() => {
    setOpen((next) => {
      const willOpen = !next;
      if (willOpen) refresh();
      return willOpen;
    });
  }, [refresh]);

  const decide = useCallback(async (requestId, decision) => {
    setBusyId(requestId);
    setError('');
    try {
      if (decision === 'approve') {
        await apiJson(`/api/v1/desktop-control/grants/requests/${requestId}/approve`, {
          method: 'POST',
          body: JSON.stringify({
            max_actions: 1,
            expires_in_seconds: APPROVAL_EXPIRES_SECONDS,
          }),
        });
      } else {
        await apiJson(`/api/v1/desktop-control/grants/requests/${requestId}/deny`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
      }
      await refresh();
    } catch (err) {
      setError(err?.message || 'Approval update failed');
    } finally {
      setBusyId(null);
    }
  }, [refresh]);

  const summaryLabel = useMemo(() => {
    if (pendingCount === 0) return 'Approvals';
    return `Approvals ${pendingCount > 99 ? '99+' : pendingCount}`;
  }, [pendingCount]);

  return (
    <div className="desktop-approval-wrap">
      <button
        className={`desktop-approval-trigger ${pendingCount > 0 ? 'has-pending' : ''}`}
        type="button"
        onClick={toggle}
        disabled={!hasSession}
        title={hasSession ? 'Desktop approvals' : 'Open a chat session first'}
        aria-label={hasSession
          ? `Desktop approvals${pendingCount ? `, ${pendingCount} pending` : ''}`
          : 'Desktop approvals unavailable'}
        aria-expanded={open}
      >
        <span className="desktop-approval-icon" aria-hidden="true">✓</span>
        <span className="desktop-approval-label">{summaryLabel}</span>
      </button>

      {open && (
        <div className="desktop-approval-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setOpen(false);
        }}>
          <section className="desktop-approval-panel" aria-label="Desktop approval requests">
            <header className="desktop-approval-header">
              <span className="desktop-approval-title">Desktop Approvals</span>
              <span className="desktop-approval-count">{pendingCount}</span>
              <button
                className="desktop-approval-close"
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close desktop approvals"
              >
                Close
              </button>
            </header>

            {error && <div className="desktop-approval-error" role="status">{error}</div>}
            {loading && pendingCount === 0 && (
              <div className="desktop-approval-empty">Checking approvals...</div>
            )}
            {!loading && pendingCount === 0 && !error && (
              <div className="desktop-approval-empty">No pending approvals.</div>
            )}

            {pendingCount > 0 && (
              <div className="desktop-approval-list">
                {requests.map((request) => {
                  const id = request.request_id;
                  const busy = busyId === id;
                  return (
                    <article className="desktop-approval-item" key={id}>
                      <div className="desktop-approval-main">
                        <div className="desktop-approval-row">
                          <span className="desktop-approval-action">{request.action}</span>
                          <span className="desktop-approval-status">{labelForStatus(request.status)}</span>
                        </div>
                        <div className="desktop-approval-meta">
                          <span>{request.capability}</span>
                          <span>{targetLabel(request)}</span>
                          <span>{expiresLabel(request.expires_at)}</span>
                        </div>
                        <div className="desktop-approval-ref">Request {compactId(id)}</div>
                      </div>
                      <div className="desktop-approval-actions">
                        <button
                          className="desktop-approval-approve"
                          type="button"
                          disabled={busy}
                          onClick={() => decide(id, 'approve')}
                        >
                          Approve
                        </button>
                        <button
                          className="desktop-approval-deny"
                          type="button"
                          disabled={busy}
                          onClick={() => decide(id, 'deny')}
                        >
                          Deny
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
