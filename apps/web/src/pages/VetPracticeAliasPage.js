import { useEffect, useState } from 'react';
import { Alert, Spinner } from 'react-bootstrap';
import { Navigate } from 'react-router-dom';
import Layout from '../components/Layout';
import { formatApiError } from '../services/apiError';
import workspaceService from '../services/workspaces';

const VetPracticeAliasPage = () => {
  const [installed, setInstalled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    workspaceService.get('vet-practice')
      .then(() => {
        if (!cancelled) setInstalled(true);
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err, 'Vet Practice is not enabled for this tenant.'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  if (installed) return <Navigate to="/workspaces/vet-practice" replace />;

  return (
    <Layout>
      <div className="workspace-page">
        {loading ? (
          <div className="text-center py-5">
            <Spinner animation="border" size="sm" variant="primary" />
          </div>
        ) : (
          <Alert variant="warning">{error}</Alert>
        )}
      </div>
    </Layout>
  );
};

export default VetPracticeAliasPage;
