import { useEffect, useState } from 'react';
import { Alert, Spinner } from 'react-bootstrap';
import { FaArrowRight, FaBriefcase, FaHeartbeat, FaHome } from 'react-icons/fa';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { formatApiError } from '../services/apiError';
import workspaceService from '../services/workspaces';
import './WorkspacePage.css';

const iconFor = (slug) => {
  if (slug === 'vet-practice') return FaHeartbeat;
  if (slug === 'alpha-control') return FaHome;
  return FaBriefcase;
};

const WorkspaceListPage = () => {
  const navigate = useNavigate();
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    workspaceService.list()
      .then((res) => {
        if (!cancelled) setWorkspaces(res.data?.workspaces || []);
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err, 'Failed to load workspaces.'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  return (
    <Layout>
      <div className="workspace-page">
        <header className="ap-page-header">
          <div>
            <h1 className="ap-page-title">Workspaces</h1>
            <p className="ap-page-subtitle">Tenant operating surfaces composed from agents, files, processes, and approvals.</p>
          </div>
        </header>

        {error && <Alert variant="warning">{error}</Alert>}
        {loading ? (
          <div className="text-center py-5">
            <Spinner animation="border" size="sm" variant="primary" />
          </div>
        ) : (
          <div className="workspace-catalog-grid">
            {workspaces.map((workspace) => {
              const Icon = iconFor(workspace.slug);
              return (
                <button
                  type="button"
                  className="ap-card workspace-card"
                  key={workspace.slug}
                  onClick={() => navigate(workspace.route)}
                >
                  <div className="ap-card-body">
                    <Icon className="workspace-card__icon" />
                    <span>
                      <strong>{workspace.label}</strong>
                      <small>{workspace.description}</small>
                    </span>
                    <FaArrowRight />
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </Layout>
  );
};

export default WorkspaceListPage;
