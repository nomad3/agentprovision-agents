/*
 * CoalitionReplayPage — Tier 5 of the visibility roadmap.
 *
 * Two views in one page:
 *   /insights/collaborations         → list of past coalition runs
 *   /insights/collaborations/{id}    → replay timeline for a run
 *
 * Backed by GET /insights/collaborations(/...) — the persisted
 * blackboard substrate from the A2A coalition system (shipped
 * 2026-04-12). Live sessions still use the existing CollaborationPanel
 * with Redis SSE; this page is for HISTORICAL replay.
 */
import { useCallback, useEffect, useState } from 'react';
import { Alert, Badge, Button, Card, Spinner, Table } from 'react-bootstrap';
import { FaArrowLeft, FaUserCircle } from 'react-icons/fa';
import { useNavigate, useParams } from 'react-router-dom';

import Layout from '../components/Layout';
import api from '../services/api';
import { formatApiError } from '../services/apiError';
import './CoalitionReplayPage.css';


function _relativeTime(iso) {
  if (!iso) return '';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return 'just now';
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m ago`;
  if (ms < 86400_000) return `${Math.floor(ms / 3600_000)}h ago`;
  return `${Math.floor(ms / 86400_000)}d ago`;
}


const CoalitionListView = () => {
  const navigate = useNavigate();
  const [rows, setRows] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get('/insights/collaborations');
        setRows(r.data?.rows || []);
      } catch (err) {
        setError(formatApiError(err, 'Failed to load coalitions.'));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>;
  if (error) return <Alert variant="danger">{error}</Alert>;
  if (!rows?.length) {
    return <Alert variant="info">No coalitions yet. A2A collaboration runs will appear here once any tenant agent triggers one.</Alert>;
  }

  return (
    <Table hover responsive>
      <thead>
        <tr>
          <th>Title</th>
          <th>Status</th>
          <th className="text-end">Entries</th>
          <th className="text-end">Agents</th>
          <th>Started</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.id} onClick={() => navigate(`/insights/collaborations/${c.id}`)} style={{ cursor: 'pointer' }}>
            <td><strong>{c.title}</strong></td>
            <td><Badge bg={c.status === 'active' ? 'success' : 'secondary'}>{c.status}</Badge></td>
            <td className="text-end">{c.entry_count}</td>
            <td className="text-end">{c.distinct_agents}</td>
            <td className="text-nowrap text-muted">{_relativeTime(c.created_at)}</td>
            <td className="text-nowrap text-muted">{_relativeTime(c.updated_at)}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
};


const CoalitionDetailView = ({ id }) => {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const r = await api.get(`/insights/collaborations/${id}`);
      setData(r.data);
    } catch (err) {
      setError(formatApiError(err, 'Failed to load coalition.'));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>;
  if (error) return <Alert variant="danger">{error}</Alert>;
  if (!data) return null;

  const { coalition, entries } = data;
  return (
    <>
      <Button variant="link" onClick={() => navigate('/insights/collaborations')} className="mb-3 px-0">
        <FaArrowLeft size={11} className="me-1" /> All coalitions
      </Button>
      <Card className="mb-3">
        <Card.Body>
          <h4 className="mb-1">{coalition.title}</h4>
          <div className="d-flex gap-2 align-items-center" style={{ fontSize: '0.85rem' }}>
            <Badge bg={coalition.status === 'active' ? 'success' : 'secondary'}>{coalition.status}</Badge>
            <span className="text-muted">{coalition.entry_count} entries · {coalition.distinct_agents} agents</span>
          </div>
        </Card.Body>
      </Card>

      {!entries.length ? (
        <Alert variant="info">No entries on this blackboard yet.</Alert>
      ) : (
        <ul className="coalition-timeline">
          {entries.map((e) => (
            <li key={e.id} className="coalition-entry">
              <div className="coalition-entry-meta">
                <Badge bg="info" className="me-2"><FaUserCircle size={10} className="me-1" />{e.author_agent_slug}</Badge>
                <Badge bg="light" text="dark" className="me-2">{e.author_role}</Badge>
                <Badge bg="secondary" className="me-2">{e.entry_type}</Badge>
                <Badge bg={e.status === 'resolved' ? 'success' : 'secondary'}>{e.status}</Badge>
                <span className="text-muted ms-2" style={{ fontSize: '0.75rem' }}>{_relativeTime(e.created_at)}</span>
              </div>
              <div className="coalition-entry-content">{e.content}</div>
              {e.resolution_reason && (
                <div className="coalition-entry-resolution">
                  Resolved by <strong>{e.resolved_by_agent}</strong>: {e.resolution_reason}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
};


const CoalitionReplayPage = () => {
  const { id } = useParams();

  return (
    <Layout>
      <div className="coalition-replay-page">
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">Coalition Replay</h1>
            <p className="ap-page-subtitle">
              Historical playback of A2A coalition runs. Live sessions
              are on the chat collaboration panel; this view is for
              after-the-fact investigation.
            </p>
          </div>
        </header>
        {id ? <CoalitionDetailView id={id} /> : <CoalitionListView />}
      </div>
    </Layout>
  );
};

export default CoalitionReplayPage;
