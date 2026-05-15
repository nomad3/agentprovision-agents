import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import agentService from '../../services/agent';

const AgentsPanel = () => {
  const navigate = useNavigate();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await agentService.getAll();
        if (!cancelled) setAgents(Array.isArray(resp.data) ? resp.data : resp.data?.agents || []);
      } catch (e) {
        if (!cancelled) setError(e.response?.data?.detail || 'Failed to load agents');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <>
      <div className="ap-sidebar-cta">
        <button type="button" onClick={() => navigate('/agents/wizard')}>+ New agent</button>
      </div>
      {loading ? (
        <div className="ap-sidebar-empty">Loading…</div>
      ) : error ? (
        <div className="ap-sidebar-empty">{error}</div>
      ) : agents.length === 0 ? (
        <div className="ap-sidebar-empty">No agents yet.</div>
      ) : (
        <ul className="ap-sidebar-list">
          {agents.map((a) => (
            <li key={a.id}>
              <button type="button" onClick={() => navigate(`/agents/${a.id}`)} title={a.name}>
                {a.name || 'Unnamed agent'}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="ap-sidebar-section-divider" />
      <ul className="ap-sidebar-list">
        <li>
          <button type="button" onClick={() => navigate('/insights/fleet-health')}>Fleet health</button>
        </li>
        <li>
          <button type="button" onClick={() => navigate('/insights/cost')}>Cost &amp; usage</button>
        </li>
      </ul>
    </>
  );
};

export default AgentsPanel;
