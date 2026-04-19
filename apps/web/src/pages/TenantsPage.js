import { useEffect, useState } from 'react';
import { Alert, Badge, Card, Col, Row, Spinner } from 'react-bootstrap';
import {
  FaBox,
  FaBuilding,
  FaCalendarCheck,
  FaCommentDots,
  FaComments,
  FaCloudUploadAlt,
  FaDatabase,
  FaProjectDiagram,
  FaNetworkWired,
  FaLayerGroup,
  FaUser,
  FaRobot,
  FaTools
} from 'react-icons/fa';
import { useAuth } from '../App';
import Layout from '../components/Layout';
import api from '../services/api';
import './TenantsPage.css';

const TenantsPage = () => {
  const { user } = useAuth();
  const [tenant, setTenant] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchTenantData = async () => {
      try {
        setLoading(true);

        // Get current user (includes tenant info)
        const userResponse = await api.get('/users/me');
        setTenant(userResponse.data.tenant);

        // Get dashboard stats for tenant metrics
        const statsResponse = await api.get('/analytics/dashboard');
        setStats(statsResponse.data);

        setError(null);
      } catch (err) {
        setError('Failed to load tenant data. Please try again.');
        console.error('Error fetching tenant data:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchTenantData();
  }, []);

  if (loading) {
    return (
      <Layout>
        <div className="text-center py-5">
          <Spinner animation="border" role="status" variant="primary">
            <span className="visually-hidden">Loading...</span>
          </Spinner>
          <p className="mt-3 text-muted">Loading tenant information...</p>
        </div>
      </Layout>
    );
  }

  if (error) {
    return (
      <Layout>
        <Alert variant="danger">{error}</Alert>
      </Layout>
    );
  }

  const StatItem = ({ icon: Icon, label, value, color = "primary" }) => (
    <Col xs={6} md={4} lg={2} className="mb-4">
      <div className="stat-item">
        <div className={`stat-icon-wrapper bg-${color}-subtle`}>
          <Icon className={`text-${color}`} size={20} />
        </div>
        <div className="stat-content">
          <div className="stat-value">{value}</div>
          <div className="stat-label">{label}</div>
        </div>
      </div>
    </Col>
  );

  return (
    <Layout>
      <div className="tenants-page">
        <div className="page-header">
          <h1 className="page-title">
            <FaBuilding className="text-primary" />
            Organizations
          </h1>
          <p className="page-subtitle">
            Manage your organizations, business units, and view usage statistics
          </p>
        </div>

        {/* Tenant Overview */}
        <Row className="g-4 mb-4">
          <Col md={4}>
            <Card className="tenant-card h-100">
              <Card.Body className="card-body-custom">
                <div className="d-flex align-items-center justify-content-between mb-3">
                  <div className="icon-pill-sm">
                    <FaBuilding size={20} />
                  </div>
                  <Badge bg="primary" className="px-3 py-2">Organization</Badge>
                </div>
                <h6 className="text-muted mb-1">Organization Name</h6>
                <div className="h4 fw-bold mb-2">{tenant?.name || 'My Organization'}</div>
                <div className="small text-muted text-truncate">Organization ID: {tenant?.id}</div>
              </Card.Body>
            </Card>
          </Col>

          <Col md={4}>
            <Card className="tenant-card h-100">
              <Card.Body className="card-body-custom">
                <div className="d-flex align-items-center justify-content-between mb-3">
                  <div className="icon-pill-sm">
                    <FaUser size={20} />
                  </div>
                  <Badge bg="success" className="px-3 py-2">Active User</Badge>
                </div>
                <h6 className="text-muted mb-1">Logged in as</h6>
                <div className="h4 fw-bold mb-2">{user?.full_name || 'User'}</div>
                <div className="small text-muted">{user?.email}</div>
              </Card.Body>
            </Card>
          </Col>

          <Col md={4}>
            <Card className="tenant-card h-100">
              <Card.Body className="card-body-custom">
                <div className="d-flex align-items-center justify-content-between mb-3">
                  <div className="icon-pill-sm">
                    <FaCalendarCheck size={20} />
                  </div>
                  <Badge bg="info" className="px-3 py-2">Status</Badge>
                </div>
                <h6 className="text-muted mb-1">Account Status</h6>
                <div className="h4 fw-bold text-success mb-2">Active</div>
                <div className="small text-success">All systems operational</div>
              </Card.Body>
            </Card>
          </Col>
        </Row>

        {/* Platform Usage Statistics */}
        {stats && (
          <Card className="tenant-card mb-4">
            <div className="card-header-transparent">
              <h5 className="mb-0">Usage Statistics</h5>
            </div>
            <Card.Body className="card-body-custom">
              <Row className="g-3">
                <StatItem
                  icon={FaRobot}
                  label="Agent Fleet"
                  value={stats.overview.total_agents}
                  color="primary"
                />
                <StatItem
                  icon={FaCloudUploadAlt}
                  label="Deployments"
                  value={stats.overview.total_deployments}
                  color="success"
                />
                <StatItem
                  icon={FaDatabase}
                  label="Datasets"
                  value={stats.overview.total_datasets}
                  color="info"
                />
                <StatItem
                  icon={FaLayerGroup}
                  label="Knowledge Bases"
                  value={stats.overview.total_vector_stores}
                  color="danger"
                />
                <StatItem
                  icon={FaCommentDots}
                  label="AI Commands"
                  value={stats.overview.total_chat_sessions}
                  color="primary"
                />
                <StatItem
                  icon={FaComments}
                  label="Total Commands"
                  value={stats.activity.total_messages}
                  color="info"
                />
                <StatItem
                  icon={FaNetworkWired}
                  label="ERP Connections"
                  value={stats.overview.total_data_sources}
                  color="success"
                />
                <StatItem
                  icon={FaProjectDiagram}
                  label="Pipelines"
                  value={stats.overview.total_pipelines}
                  color="warning"
                />
                <StatItem
                  icon={FaTools}
                  label="Tools"
                  value={stats.overview.total_tools}
                  color="secondary"
                />
              </Row>
            </Card.Body>
          </Card>
        )}

        {/* Tenant Information */}
        <Card className="tenant-card">
          <div className="card-header-transparent">
            <h5 className="mb-0">Organization Details</h5>
          </div>
          <Card.Body className="card-body-custom">
            <Alert variant="info" className="info-alert mb-4">
              <strong>Data Isolation:</strong> All your data is completely isolated from other organizations.
              Your agents, datasets, AI commands, and configurations are private to your organization.
            </Alert>

            <div>
              <h6 className="mb-3">What is an Organization?</h6>
              <p className="text-muted mb-0">
                An organization represents a company or business unit in your platform. All users
                within an organization share access to the same AI agent fleet, datasets, and configurations.
                Data is completely isolated between organizations for security and compliance.
              </p>
            </div>
          </Card.Body>
        </Card>
      </div>
    </Layout>
  );
};

export default TenantsPage;
