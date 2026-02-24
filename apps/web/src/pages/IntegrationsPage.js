import { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Modal,
  Row,
  Spinner,
  Table
} from 'react-bootstrap';
import {
  FaSyncAlt,
  FaCalendarAlt,
  FaCheckCircle,
  FaCloudUploadAlt,
  FaDatabase,
  FaExclamationTriangle,
  FaBolt,
  FaPen,
  FaPlay,
  FaPlus,
  FaTrash,
  FaTimesCircle
} from 'react-icons/fa';
import Layout from '../components/Layout';
import SkillsConfigPanel from '../components/SkillsConfigPanel';
import connectorService from '../services/connector';
import dataPipelineService from '../services/dataPipeline';
import './IntegrationsPage.css';

// Connector type configurations
const CONNECTOR_TYPES = {
  snowflake: { label: 'Snowflake', icon: '❄️', color: '#29B5E8' },
  postgres: { label: 'PostgreSQL', icon: '🐘', color: '#336791' },
  mysql: { label: 'MySQL', icon: '🐬', color: '#00758F' },
  databricks: { label: 'Databricks', icon: '⚡', color: '#FF3621' },
  s3: { label: 'Amazon S3', icon: '📦', color: '#FF9900' },
  gcs: { label: 'Google Cloud Storage', icon: '☁️', color: '#4285F4' },
  api: { label: 'REST API', icon: '🔗', color: '#6C757D' }
};

const CONNECTOR_FIELDS = {
  snowflake: [
    { name: 'account', label: 'Account', type: 'text', placeholder: 'xy12345.us-east-1', required: true },
    { name: 'user', label: 'Username', type: 'text', required: true },
    { name: 'password', label: 'Password', type: 'password', required: true },
    { name: 'warehouse', label: 'Warehouse', type: 'text', required: true },
    { name: 'database', label: 'Database', type: 'text', required: true },
    { name: 'schema', label: 'Schema', type: 'text', placeholder: 'PUBLIC' }
  ],
  postgres: [
    { name: 'host', label: 'Host', type: 'text', required: true },
    { name: 'port', label: 'Port', type: 'number', placeholder: '5432' },
    { name: 'database', label: 'Database', type: 'text', required: true },
    { name: 'user', label: 'Username', type: 'text', required: true },
    { name: 'password', label: 'Password', type: 'password', required: true }
  ],
  mysql: [
    { name: 'host', label: 'Host', type: 'text', required: true },
    { name: 'port', label: 'Port', type: 'number', placeholder: '3306' },
    { name: 'database', label: 'Database', type: 'text', required: true },
    { name: 'user', label: 'Username', type: 'text', required: true },
    { name: 'password', label: 'Password', type: 'password', required: true }
  ],
  databricks: [
    { name: 'host', label: 'Workspace URL', type: 'text', required: true },
    { name: 'token', label: 'Access Token', type: 'password', required: true },
    { name: 'http_path', label: 'SQL Warehouse Path', type: 'text', required: true }
  ],
  s3: [
    { name: 'bucket', label: 'Bucket Name', type: 'text', required: true },
    { name: 'region', label: 'Region', type: 'text', placeholder: 'us-east-1' },
    { name: 'access_key', label: 'Access Key ID', type: 'text', required: true },
    { name: 'secret_key', label: 'Secret Access Key', type: 'password', required: true }
  ],
  gcs: [
    { name: 'bucket', label: 'Bucket Name', type: 'text', required: true },
    { name: 'project_id', label: 'Project ID', type: 'text', required: true }
  ],
  api: [
    { name: 'base_url', label: 'Base URL', type: 'text', required: true },
    { name: 'auth_type', label: 'Auth Type', type: 'select', options: ['none', 'api_key', 'bearer'] },
    { name: 'api_key', label: 'API Key', type: 'password' }
  ]
};

const IntegrationsPage = () => {
  const [connectors, setConnectors] = useState([]);
  const [syncs, setSyncs] = useState([]);
  const [loading, setLoading] = useState(true);

  // Modal states
  const [showConnectorModal, setShowConnectorModal] = useState(false);
  const [showSyncModal, setShowSyncModal] = useState(false);
  const [editingConnector, setEditingConnector] = useState(null);

  // Form states
  const [connectorForm, setConnectorForm] = useState({ name: '', description: '', type: 'snowflake', config: {} });
  const [syncForm, setSyncForm] = useState({ connector_id: '', table_name: '', frequency: 'daily', mode: 'full' });

  // Action states
  const [testing, setTesting] = useState(null);
  const [syncing, setSyncing] = useState(null);
  const [testResult, setTestResult] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [connectorsRes, syncsRes] = await Promise.all([
        connectorService.getAll(),
        dataPipelineService.getAll().catch(() => ({ data: [] }))
      ]);
      setConnectors(connectorsRes.data || []);
      setSyncs((syncsRes.data || []).filter(s => s.config?.type === 'connector_sync'));
    } catch (err) {
      setError('Failed to load integrations');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // Stats calculation
  const stats = {
    total: connectors.length,
    active: connectors.filter(c => c.status === 'active').length,
    pending: connectors.filter(c => c.status === 'pending').length,
    error: connectors.filter(c => c.status === 'error').length,
    syncsActive: syncs.filter(s => s.config?.is_active !== false).length
  };

  // Connector handlers
  const handleOpenConnectorModal = (connector = null) => {
    if (connector) {
      setEditingConnector(connector);
      setConnectorForm({
        name: connector.name,
        description: connector.description || '',
        type: connector.type,
        config: connector.config || {}
      });
    } else {
      setEditingConnector(null);
      setConnectorForm({ name: '', description: '', type: 'snowflake', config: {} });
    }
    setTestResult(null);
    setShowConnectorModal(true);
  };

  const handleSaveConnector = async () => {
    try {
      setSaving(true);
      if (editingConnector) {
        await connectorService.update(editingConnector.id, connectorForm);
        setSuccess('Connector updated');
      } else {
        await connectorService.create(connectorForm);
        setSuccess('Connector created');
      }
      setShowConnectorModal(false);
      fetchData();
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError('Failed to save connector');
    } finally {
      setSaving(false);
    }
  };

  const handleTestConnector = async (connectorId = null) => {
    try {
      if (connectorId) {
        setTesting(connectorId);
        await connectorService.testExisting(connectorId);
        setSuccess('Connection successful!');
        fetchData();
      } else {
        setTesting(true);
        const res = await connectorService.testConnection(connectorForm.type, connectorForm.config);
        setTestResult(res.data);
      }
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError('Connection test failed');
      if (!connectorId) {
        setTestResult({ success: false, message: err.response?.data?.detail || 'Connection failed' });
      }
    } finally {
      setTesting(null);
    }
  };

  const handleDeleteConnector = async (id) => {
    if (window.confirm('Delete this connector? This will also remove any scheduled syncs.')) {
      try {
        await connectorService.delete(id);
        setSuccess('Connector deleted');
        fetchData();
        setTimeout(() => setSuccess(null), 3000);
      } catch (err) {
        setError('Failed to delete connector');
      }
    }
  };

  // Sync handlers
  const handleOpenSyncModal = (connector = null) => {
    setSyncForm({
      connector_id: connector?.id || '',
      table_name: '',
      frequency: 'daily',
      mode: 'full'
    });
    setShowSyncModal(true);
  };

  const handleCreateSync = async () => {
    try {
      setSaving(true);
      const connector = connectors.find(c => c.id === syncForm.connector_id);
      await dataPipelineService.create({
        name: `Sync: ${connector?.name || 'Unknown'} - ${syncForm.table_name}`,
        config: {
          type: 'connector_sync',
          connector_id: syncForm.connector_id,
          table_name: syncForm.table_name,
          frequency: syncForm.frequency,
          mode: syncForm.mode
        }
      });
      setSuccess('Sync schedule created');
      setShowSyncModal(false);
      fetchData();
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError('Failed to create sync');
    } finally {
      setSaving(false);
    }
  };

  const handleRunSync = async (syncId) => {
    try {
      setSyncing(syncId);
      await dataPipelineService.execute(syncId);
      setSuccess('Sync started! Check back for results.');
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError('Failed to start sync');
    } finally {
      setSyncing(null);
    }
  };

  const getStatusBadge = (status) => {
    const configs = {
      active: { bg: 'success', icon: FaCheckCircle, text: 'Active' },
      error: { bg: 'danger', icon: FaTimesCircle, text: 'Error' },
      pending: { bg: 'warning', icon: FaExclamationTriangle, text: 'Pending' }
    };
    const config = configs[status] || configs.pending;
    return <Badge bg={config.bg}><config.icon className="me-1" size={10} />{config.text}</Badge>;
  };

  const renderOverview = () => (
    <div className="integrations-overview">

      {/* Skills Config Panel - shown when OpenClaw instance is running */}
      <SkillsConfigPanel />

      {/* Stats Cards */}
      <Row className="g-4 mb-4">
        <Col md={3}>
          <Card className="stat-card stat-total">
            <Card.Body>
              <div className="stat-icon"><FaDatabase size={24} /></div>
              <div className="stat-content">
                <div className="stat-value">{stats.total}</div>
                <div className="stat-label">System Connectors</div>
              </div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="stat-card stat-active">
            <Card.Body>
              <div className="stat-icon"><FaCheckCircle size={24} /></div>
              <div className="stat-content">
                <div className="stat-value">{stats.active}</div>
                <div className="stat-label">Active</div>
              </div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="stat-card stat-syncs">
            <Card.Body>
              <div className="stat-icon"><FaSyncAlt size={24} /></div>
              <div className="stat-content">
                <div className="stat-value">{stats.syncsActive}</div>
                <div className="stat-label">Active Syncs</div>
              </div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="stat-card stat-error">
            <Card.Body>
              <div className="stat-icon"><FaExclamationTriangle size={24} /></div>
              <div className="stat-content">
                <div className="stat-value">{stats.error}</div>
                <div className="stat-label">Need Attention</div>
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      {/* Recent Activity */}
      <Row className="g-4">
        <Col lg={8}>
          <Card className="activity-card">
            <Card.Header className="d-flex justify-content-between align-items-center">
              <h5 className="mb-0"><FaBolt className="me-2" />Connected Systems</h5>
              <Button variant="primary" size="sm" onClick={() => handleOpenConnectorModal()}>
                <FaPlus className="me-2" />Add Connector
              </Button>
            </Card.Header>
            <Card.Body className="p-0">
              {connectors.length === 0 ? (
                <div className="text-center py-5">
                  <FaCloudUploadAlt size={48} className="text-muted mb-3" />
                  <h5>No connectors yet</h5>
                  <p className="text-muted">Connect your first ERP or system to start syncing data</p>
                  <Button variant="primary" onClick={() => handleOpenConnectorModal()}>
                    <FaPlus className="me-2" />Connect Your First System
                  </Button>
                </div>
              ) : (
                <Table hover className="mb-0 connectors-table">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Status</th>
                      <th>Last Tested</th>
                      <th className="text-end">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {connectors.map(connector => (
                      <tr key={connector.id}>
                        <td>
                          <div className="d-flex align-items-center">
                            <span className="connector-icon me-2">
                              {CONNECTOR_TYPES[connector.type]?.icon || '🔌'}
                            </span>
                            <div>
                              <div className="fw-medium">{connector.name}</div>
                              <small className="text-muted">{CONNECTOR_TYPES[connector.type]?.label}</small>
                            </div>
                          </div>
                        </td>
                        <td>{getStatusBadge(connector.status)}</td>
                        <td>
                          <small className="text-muted">
                            {connector.last_test_at
                              ? new Date(connector.last_test_at).toLocaleDateString()
                              : 'Never'}
                          </small>
                        </td>
                        <td className="text-end">
                          <Button
                            variant="outline-success"
                            size="sm"
                            className="me-1"
                            onClick={() => handleTestConnector(connector.id)}
                            disabled={testing === connector.id}
                          >
                            {testing === connector.id ? <Spinner size="sm" /> : <FaPlay />}
                          </Button>
                          <Button
                            variant="outline-primary"
                            size="sm"
                            className="me-1"
                            onClick={() => handleOpenSyncModal(connector)}
                            disabled={connector.status !== 'active'}
                          >
                            <FaSyncAlt />
                          </Button>
                          <Button
                            variant="outline-secondary"
                            size="sm"
                            className="me-1"
                            onClick={() => handleOpenConnectorModal(connector)}
                          >
                            <FaPen />
                          </Button>
                          <Button
                            variant="outline-danger"
                            size="sm"
                            onClick={() => handleDeleteConnector(connector.id)}
                          >
                            <FaTrash />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={4}>
          <Card className="syncs-card">
            <Card.Header>
              <h5 className="mb-0"><FaCalendarAlt className="me-2" />Data Syncs</h5>
            </Card.Header>
            <Card.Body className="p-0">
              {syncs.length === 0 ? (
                <div className="text-center py-4">
                  <FaSyncAlt size={32} className="text-muted mb-2" />
                  <p className="text-muted mb-0 small">No data syncs scheduled</p>
                </div>
              ) : (
                <div className="syncs-list">
                  {syncs.slice(0, 5).map(sync => {
                    // Find connector for display purposes (currently unused but kept for future)
                    const connectorForSync = connectors.find(c => c.id === sync.config?.connector_id);
                    return (
                      <div key={sync.id} className="sync-item">
                        <div className="sync-info">
                          <div className="sync-name">{sync.name}</div>
                          <small className="text-muted">
                            {sync.config?.frequency || 'Manual'} • {sync.config?.mode || 'Full'}
                          </small>
                        </div>
                        <Button
                          variant="link"
                          size="sm"
                          onClick={() => handleRunSync(sync.id)}
                          disabled={syncing === sync.id}
                        >
                          {syncing === sync.id ? <Spinner size="sm" /> : <FaPlay />}
                        </Button>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </div>
  );

  const renderConnectorForm = () => {
    const fields = CONNECTOR_FIELDS[connectorForm.type] || [];
    return fields.map(field => (
      <Form.Group key={field.name} className="mb-3">
        <Form.Label>{field.label}{field.required && <span className="text-danger">*</span>}</Form.Label>
        {field.type === 'select' ? (
          <Form.Select
            value={connectorForm.config[field.name] || ''}
            onChange={(e) => setConnectorForm(prev => ({
              ...prev,
              config: { ...prev.config, [field.name]: e.target.value }
            }))}
          >
            <option value="">Select...</option>
            {field.options?.map(opt => <option key={opt} value={opt}>{opt}</option>)}
          </Form.Select>
        ) : (
          <Form.Control
            type={field.type}
            placeholder={field.placeholder}
            value={connectorForm.config[field.name] || ''}
            onChange={(e) => setConnectorForm(prev => ({
              ...prev,
              config: { ...prev.config, [field.name]: e.target.value }
            }))}
            required={field.required}
          />
        )}
      </Form.Group>
    ));
  };

  return (
    <Layout>
      <div className="integrations-page">
        <div className="page-header mb-4">
          <div>
            <h1 className="page-title">
              <FaDatabase className="me-2" />
              System Integrations
            </h1>
            <p className="page-subtitle text-muted">
              Connect ERPs, banks, and systems across your organization
            </p>
          </div>
          <div className="header-actions">
            <Button variant="outline-primary" className="me-2" onClick={() => handleOpenSyncModal()}>
              <FaSyncAlt className="me-2" />New Data Sync
            </Button>
            <Button variant="primary" onClick={() => handleOpenConnectorModal()}>
              <FaPlus className="me-2" />Add System
            </Button>
          </div>
        </div>

        {error && <Alert variant="danger" onClose={() => setError(null)} dismissible>{error}</Alert>}
        {success && <Alert variant="success" onClose={() => setSuccess(null)} dismissible>{success}</Alert>}

        {loading ? (
          <div className="text-center py-5">
            <Spinner animation="border" variant="primary" />
            <p className="text-muted mt-3">Loading integrations...</p>
          </div>
        ) : (
          renderOverview()
        )}

        {/* Connector Modal */}
        <Modal show={showConnectorModal} onHide={() => setShowConnectorModal(false)} size="lg">
          <Modal.Header closeButton>
            <Modal.Title>{editingConnector ? 'Edit Connector' : 'Add New Connector'}</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form>
              <Row>
                <Col md={6}>
                  <Form.Group className="mb-3">
                    <Form.Label>Name<span className="text-danger">*</span></Form.Label>
                    <Form.Control
                      type="text"
                      placeholder="e.g., Production Snowflake"
                      value={connectorForm.name}
                      onChange={(e) => setConnectorForm({ ...connectorForm, name: e.target.value })}
                      required
                    />
                  </Form.Group>
                </Col>
                <Col md={6}>
                  <Form.Group className="mb-3">
                    <Form.Label>Type<span className="text-danger">*</span></Form.Label>
                    <Form.Select
                      value={connectorForm.type}
                      onChange={(e) => setConnectorForm({ ...connectorForm, type: e.target.value, config: {} })}
                      disabled={!!editingConnector}
                    >
                      {Object.entries(CONNECTOR_TYPES).map(([key, cfg]) => (
                        <option key={key} value={key}>{cfg.icon} {cfg.label}</option>
                      ))}
                    </Form.Select>
                  </Form.Group>
                </Col>
              </Row>
              <Form.Group className="mb-3">
                <Form.Label>Description</Form.Label>
                <Form.Control
                  as="textarea"
                  rows={2}
                  placeholder="Optional description..."
                  value={connectorForm.description}
                  onChange={(e) => setConnectorForm({ ...connectorForm, description: e.target.value })}
                />
              </Form.Group>
              <hr />
              <h6 className="mb-3">Connection Settings</h6>
              {renderConnectorForm()}
              {testResult && (
                <Alert variant={testResult.success ? 'success' : 'danger'} className="mt-3">
                  {testResult.success ? <FaCheckCircle className="me-2" /> : <FaTimesCircle className="me-2" />}
                  {testResult.message}
                </Alert>
              )}
            </Form>
          </Modal.Body>
          <Modal.Footer>
            <Button variant="outline-secondary" onClick={() => handleTestConnector()} disabled={testing}>
              {testing ? <Spinner size="sm" className="me-2" /> : <FaPlay className="me-2" />}
              Test Connection
            </Button>
            <Button variant="secondary" onClick={() => setShowConnectorModal(false)}>Cancel</Button>
            <Button variant="primary" onClick={handleSaveConnector} disabled={saving || !connectorForm.name}>
              {saving ? <Spinner size="sm" /> : (editingConnector ? 'Update' : 'Create')}
            </Button>
          </Modal.Footer>
        </Modal>

        {/* Sync Modal */}
        <Modal show={showSyncModal} onHide={() => setShowSyncModal(false)}>
          <Modal.Header closeButton>
            <Modal.Title>Schedule Data Sync</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <Form>
              <Form.Group className="mb-3">
                <Form.Label>Connector<span className="text-danger">*</span></Form.Label>
                <Form.Select
                  value={syncForm.connector_id}
                  onChange={(e) => setSyncForm({ ...syncForm, connector_id: e.target.value })}
                  required
                >
                  <option value="">Select a connector...</option>
                  {connectors.filter(c => c.status === 'active').map(c => (
                    <option key={c.id} value={c.id}>
                      {CONNECTOR_TYPES[c.type]?.icon} {c.name}
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>
              <Form.Group className="mb-3">
                <Form.Label>Table/Query Name<span className="text-danger">*</span></Form.Label>
                <Form.Control
                  type="text"
                  placeholder="e.g., customers, orders"
                  value={syncForm.table_name}
                  onChange={(e) => setSyncForm({ ...syncForm, table_name: e.target.value })}
                  required
                />
              </Form.Group>
              <Row>
                <Col>
                  <Form.Group className="mb-3">
                    <Form.Label>Frequency</Form.Label>
                    <Form.Select
                      value={syncForm.frequency}
                      onChange={(e) => setSyncForm({ ...syncForm, frequency: e.target.value })}
                    >
                      <option value="hourly">Hourly</option>
                      <option value="daily">Daily</option>
                      <option value="weekly">Weekly</option>
                    </Form.Select>
                  </Form.Group>
                </Col>
                <Col>
                  <Form.Group className="mb-3">
                    <Form.Label>Sync Mode</Form.Label>
                    <Form.Select
                      value={syncForm.mode}
                      onChange={(e) => setSyncForm({ ...syncForm, mode: e.target.value })}
                    >
                      <option value="full">Full Refresh</option>
                      <option value="incremental">Incremental</option>
                    </Form.Select>
                  </Form.Group>
                </Col>
              </Row>
            </Form>
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowSyncModal(false)}>Cancel</Button>
            <Button
              variant="primary"
              onClick={handleCreateSync}
              disabled={saving || !syncForm.connector_id || !syncForm.table_name}
            >
              {saving ? <Spinner size="sm" /> : 'Schedule Sync'}
            </Button>
          </Modal.Footer>
        </Modal>
      </div>
    </Layout>
  );
};

export default IntegrationsPage;
