/*
 * TenantHealthPage — Op-2 of the visibility roadmap.
 *
 * Superuser-only cross-tenant health dashboard. Each row is one tenant
 * over the last 24h: chat volume, fallback rate, chain-exhausted count,
 * last activity, primary CLI in use.
 *
 * Curated triage view — operators drill into a tenant's normal pages
 * for per-message detail.
 */
import { useEffect, useState } from 'react';
import { Alert, Badge, Card, Spinner, Table } from 'react-bootstrap';

import Layout from '../components/Layout';
import api from '../services/api';
import { formatApiError } from '../services/apiError';
import './TenantHealthPage.css';


function _relativeTime(iso) {
  if (!iso) return 'never';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'just now';
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86400_000) return `${Math.floor(ms / 3600_000)}h ago`;
  return `${Math.floor(ms / 86400_000)}d ago`;
}


function _cliLabel(p) {
  if (!p) return '—';
  return {
    claude_code: 'Claude Code',
    copilot_cli: 'GitHub Copilot CLI',
    codex: 'Codex CLI',
    gemini_cli: 'Gemini CLI',
    opencode: 'OpenCode',
    local_gemma: 'Local Gemma',
  }[p] || p;
}


function _fallbackBadgeBg(rate) {
  if (rate < 0.05) return 'success';
  if (rate < 0.20) return 'warning';
  return 'danger';
}


const TenantHealthPage = () => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get('/admin/tenant-health');
        setData(r.data);
      } catch (err) {
        if (err.response?.status === 403) {
          setError('Superuser access required.');
        } else {
          setError(formatApiError(err, 'Failed to load tenant health.'));
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <Layout>
      <div className="tenant-health-page">
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">Tenant Health</h1>
            <p className="ap-page-subtitle">
              Cross-tenant snapshot — last 24h. Stalled tenants and
              high-fallback tenants surface here first.
            </p>
          </div>
        </header>

        {loading && <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>}
        {error && <Alert variant="danger">{error}</Alert>}

        {data && (
          <Card>
            <Card.Body className="p-0">
              <Table hover responsive className="mb-0">
                <thead>
                  <tr>
                    <th>Tenant</th>
                    <th className="text-end">Users</th>
                    <th className="text-end">Active agents</th>
                    <th className="text-end">Turns 24h</th>
                    <th className="text-end">Fallback</th>
                    <th className="text-end">Exhausted</th>
                    <th>Primary CLI</th>
                    <th>Last activity</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.tenant_id} className={r.turn_count_24h === 0 ? 'tenant-row-stalled' : ''}>
                      <td><strong>{r.tenant_name}</strong></td>
                      <td className="text-end">{r.user_count}</td>
                      <td className="text-end">{r.active_agent_count}</td>
                      <td className="text-end">{r.turn_count_24h}</td>
                      <td className="text-end">
                        {r.turn_count_24h === 0 ? (
                          <span className="text-muted">—</span>
                        ) : (
                          <Badge bg={_fallbackBadgeBg(r.fallback_rate_24h)}>
                            {(r.fallback_rate_24h * 100).toFixed(1)}%
                          </Badge>
                        )}
                      </td>
                      <td className="text-end">
                        {r.chain_exhausted_24h > 0 ? (
                          <Badge bg="danger">{r.chain_exhausted_24h}</Badge>
                        ) : (
                          <span className="text-muted">0</span>
                        )}
                      </td>
                      <td><span className="text-muted">{_cliLabel(r.primary_cli)}</span></td>
                      <td className="text-nowrap text-muted">{_relativeTime(r.last_activity_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card.Body>
          </Card>
        )}
      </div>
    </Layout>
  );
};

export default TenantHealthPage;
