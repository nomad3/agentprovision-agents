import { useEffect, useState, useMemo } from 'react';
import { Alert, Badge, Button, Col, Form, Modal, Row, Spinner } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import agentService from '../services/agent';

const AgentsPage = () => {
  const { t } = useTranslation('agents');
  const navigate = useNavigate();
  const [agents, setAgents] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    Promise.all([
      agentService.getAll().then(r => setAgents(r.data || [])),
      agentService.getTasks().then(r => setTasks(r.data || [])).catch(() => {}),
    ])
      .catch(err => { console.error(err); setError(t('errors.load')); })
      .finally(() => setLoading(false));
  }, [t]);

  const tasksByAgent = useMemo(() => {
    const map = {};
    tasks.forEach(task => {
      const aid = task.assigned_agent_id;
      if (!aid) return;
      if (!map[aid]) map[aid] = { active: 0, completed: 0, total: 0 };
      map[aid].total++;
      if (task.status === 'completed') map[aid].completed++;
      else if (['queued', 'thinking', 'executing'].includes(task.status)) map[aid].active++;
    });
    return map;
  }, [tasks]);

  const filtered = agents.filter(a =>
    a.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    a.description?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleDelete = async (agent) => {
    try {
      setSubmitting(true);
      await agentService.delete(agent.id);
      setDeleteConfirm(null);
      setSuccess(t('success.deleted', { name: agent.name }));
      setAgents(prev => prev.filter(a => a.id !== agent.id));
      setTimeout(() => setSuccess(''), 3000);
    } catch (err) {
      console.error(err);
      setError(t('errors.delete'));
    } finally {
      setSubmitting(false);
    }
  };

  const getSkills = (agent) => {
    const configSkills = agent.config?.skills || agent.config?.tools || [];
    const agentSkills = (agent.skills || []).map(s => s.skill_name);
    return [...new Set([...configSkills, ...agentSkills])];
  };

  const statusColor = (s) => s === 'active' ? '#22c55e' : s === 'error' ? '#ef4444' : '#94a3b8';

  const ROLE_COLORS = { analyst: '#6f42c1', manager: '#0d6efd', specialist: '#fd7e14' };
  const AUTONOMY_LABELS = { full: 'Full Auto', supervised: 'Supervised', approval_required: 'Approval Req.' };

  const cardStyle = {
    background: 'var(--surface-elevated)',
    border: '1px solid var(--color-border)',
    borderRadius: 8,
    padding: '20px 24px',
    cursor: 'pointer',
    transition: 'transform 0.15s ease, box-shadow 0.15s ease',
  };

  return (
    <Layout>
      <div style={{ maxWidth: 1100 }}>
        {/* Header */}
        <div className="d-flex justify-content-between align-items-start mb-4">
          <div>
            <h4 style={{ fontWeight: 600, marginBottom: 4, color: 'var(--color-foreground)' }}>
              {t('title')}
            </h4>
            <p style={{ fontSize: '0.85rem', color: 'var(--color-muted)', margin: 0 }}>
              {t('subtitle', { count: agents.length })}
            </p>
          </div>
          <Button
            variant="outline-secondary"
            size="sm"
            onClick={() => navigate('/agents/wizard')}
            style={{ fontSize: '0.82rem' }}
          >
            + {t('agentWizard')}
          </Button>
        </div>

        {error && <Alert variant="danger" dismissible onClose={() => setError('')} style={{ fontSize: '0.82rem' }}>{error}</Alert>}
        {success && <Alert variant="success" dismissible onClose={() => setSuccess('')} style={{ fontSize: '0.82rem' }}>{success}</Alert>}

        {/* Search */}
        <div style={{ marginBottom: 20 }}>
          <Form.Control
            type="text"
            size="sm"
            placeholder={t('searchPlaceholder')}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            style={{ maxWidth: 300, fontSize: '0.82rem' }}
          />
        </div>

        {/* Card Grid */}
        {loading ? (
          <div className="text-center py-5">
            <Spinner animation="border" size="sm" variant="primary" />
            <p className="mt-2 text-muted" style={{ fontSize: '0.82rem' }}>{t('loading')}</p>
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ ...cardStyle, textAlign: 'center', padding: '48px 24px', cursor: 'default' }}>
            <p style={{ fontSize: '0.88rem', color: 'var(--color-foreground)', fontWeight: 500, marginBottom: 4 }}>
              {searchTerm ? t('noAgentsMatch') : t('noAgentsYet')}
            </p>
            <p style={{ fontSize: '0.78rem', color: 'var(--color-muted)', marginBottom: 16 }}>
              {searchTerm ? t('tryDifferent') : t('createFirst')}
            </p>
            {!searchTerm && (
              <Button variant="primary" size="sm" onClick={() => navigate('/agents/wizard')}>
                {t('createAgent')}
              </Button>
            )}
          </div>
        ) : (
          <Row className="g-3">
            {filtered.map((agent) => {
              const skills = getSkills(agent);
              const stats = tasksByAgent[agent.id] || { active: 0, completed: 0, total: 0 };
              const successRate = stats.total > 0 ? Math.round((stats.completed / stats.total) * 100) : 0;

              return (
                <Col key={agent.id} md={6} xl={4}>
                  <div
                    style={cardStyle}
                    onClick={() => navigate(`/agents/${agent.id}`)}
                    onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)'; }}
                    onMouseLeave={e => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = 'none'; }}
                  >
                    {/* Header: name + status + model */}
                    <div className="d-flex align-items-center justify-content-between mb-2">
                      <div className="d-flex align-items-center gap-2">
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: statusColor(agent.status), flexShrink: 0 }} />
                        <span style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--color-foreground)' }}>
                          {agent.name}
                        </span>
                      </div>
                      <span style={{
                        fontSize: '0.68rem', padding: '2px 8px', borderRadius: 4,
                        background: 'var(--surface-contrast, rgba(255,255,255,0.06))',
                        color: 'var(--color-muted)', fontWeight: 500,
                      }}>
                        {agent.config?.model || agent.model || 'gpt-4'}
                      </span>
                    </div>

                    {/* Description */}
                    <p style={{
                      fontSize: '0.78rem', color: 'var(--color-muted)', margin: '0 0 10px 0',
                      display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                    }}>
                      {agent.description || 'No description'}
                    </p>

                    {/* Role + autonomy badges */}
                    <div className="d-flex gap-1 mb-2 flex-wrap">
                      {agent.role && (
                        <Badge bg="none" style={{ fontSize: '0.65rem', backgroundColor: ROLE_COLORS[agent.role] || '#6c757d' }}>
                          {agent.role}
                        </Badge>
                      )}
                      <Badge bg="none" style={{ fontSize: '0.65rem', backgroundColor: 'rgba(255,255,255,0.1)', color: 'var(--color-muted)' }}>
                        {AUTONOMY_LABELS[agent.autonomy_level] || agent.autonomy_level || 'supervised'}
                      </Badge>
                    </div>

                    {/* Skills pills */}
                    {skills.length > 0 && (
                      <div className="d-flex gap-1 mb-2 flex-wrap">
                        {skills.slice(0, 4).map(s => (
                          <span key={s} style={{
                            fontSize: '0.65rem', padding: '1px 6px', borderRadius: 3,
                            background: 'rgba(77,171,247,0.12)', color: '#4dabf7',
                          }}>
                            {s.replace(/_/g, ' ')}
                          </span>
                        ))}
                        {skills.length > 4 && (
                          <span style={{ fontSize: '0.65rem', color: 'var(--color-muted)' }}>
                            +{skills.length - 4} more
                          </span>
                        )}
                      </div>
                    )}

                    {/* Stats row */}
                    <div className="d-flex align-items-center gap-3" style={{ fontSize: '0.72rem', color: 'var(--color-muted)' }}>
                      <span>{stats.active} active</span>
                      <span>{stats.completed} completed</span>
                      {stats.total > 0 && (
                        <div className="d-flex align-items-center gap-1">
                          <div style={{ width: 40, height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.1)' }}>
                            <div style={{ width: `${successRate}%`, height: '100%', borderRadius: 2, background: '#22c55e' }} />
                          </div>
                          <span>{successRate}%</span>
                        </div>
                      )}
                    </div>

                    {/* Delete button (stop propagation) */}
                    <div className="d-flex justify-content-end mt-2">
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeleteConfirm(agent); }}
                        style={{
                          background: 'none', border: '1px solid var(--color-border)',
                          borderRadius: 4, padding: '2px 8px', fontSize: '0.68rem',
                          color: '#ef4444', cursor: 'pointer',
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </Col>
              );
            })}
          </Row>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      <Modal show={!!deleteConfirm} onHide={() => setDeleteConfirm(null)} centered size="sm">
        <Modal.Body className="text-center py-4">
          <p style={{ fontSize: '0.88rem', fontWeight: 500, marginBottom: 8 }}>
            {t('deleteModal.title', { name: deleteConfirm?.name })}
          </p>
          <p style={{ fontSize: '0.78rem', color: 'var(--color-muted)', marginBottom: 20 }}>
            {t('deleteModal.warning')}
          </p>
          <div className="d-flex justify-content-center gap-2">
            <Button variant="outline-secondary" size="sm" onClick={() => setDeleteConfirm(null)}>
              {t('deleteModal.cancel')}
            </Button>
            <Button variant="danger" size="sm" onClick={() => handleDelete(deleteConfirm)} disabled={submitting}>
              {submitting ? t('deleteModal.deleting') : t('deleteModal.delete')}
            </Button>
          </div>
        </Modal.Body>
      </Modal>
    </Layout>
  );
};

export default AgentsPage;
