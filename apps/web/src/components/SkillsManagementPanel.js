import { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Spinner,
} from 'react-bootstrap';
import {
  FaCog,
  FaCopy,
  FaPlus,
  FaStar,
  FaTrash,
} from 'react-icons/fa';
import { skillsService } from '../services/skills';

const SkillsManagementPanel = () => {
  const [skills, setSkills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [creating, setCreating] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);
  const [newSkill, setNewSkill] = useState({
    name: '',
    description: '',
    skill_type: 'scoring',
    config: '{}',
  });

  const fetchSkills = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await skillsService.getSkills();
      setSkills(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Failed to load skills:', err);
      setError('Failed to load skills');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  // Group skills by skill_type
  const groupedSkills = skills.reduce((groups, skill) => {
    const type = skill.skill_type || 'other';
    if (!groups[type]) groups[type] = [];
    groups[type].push(skill);
    return groups;
  }, {});

  const handleCreateSkill = async (e) => {
    e.preventDefault();
    if (!newSkill.name.trim()) {
      setError('Skill name is required');
      setTimeout(() => setError(null), 4000);
      return;
    }

    let parsedConfig;
    try {
      parsedConfig = JSON.parse(newSkill.config);
    } catch {
      setError('Config must be valid JSON');
      setTimeout(() => setError(null), 4000);
      return;
    }

    try {
      setCreating(true);
      await skillsService.createSkill({
        name: newSkill.name.trim(),
        description: newSkill.description.trim(),
        skill_type: newSkill.skill_type,
        config: parsedConfig,
      });
      setSuccess(`Skill "${newSkill.name}" created`);
      setTimeout(() => setSuccess(null), 4000);
      setNewSkill({ name: '', description: '', skill_type: 'scoring', config: '{}' });
      setShowCreateForm(false);
      await fetchSkills();
    } catch (err) {
      const detail = err.response?.data?.detail || 'Failed to create skill';
      setError(detail);
      setTimeout(() => setError(null), 5000);
    } finally {
      setCreating(false);
    }
  };

  const handleCloneSkill = async (skill) => {
    try {
      setActionLoading(skill.id);
      await skillsService.cloneSkill(skill.id);
      setSuccess(`Cloned "${skill.name}"`);
      setTimeout(() => setSuccess(null), 4000);
      await fetchSkills();
    } catch (err) {
      const detail = err.response?.data?.detail || 'Failed to clone skill';
      setError(detail);
      setTimeout(() => setError(null), 5000);
    } finally {
      setActionLoading(null);
    }
  };

  const handleDeleteSkill = async (skill) => {
    if (!window.confirm(`Delete skill "${skill.name}"? This cannot be undone.`)) return;

    try {
      setActionLoading(skill.id);
      await skillsService.deleteSkill(skill.id);
      setSuccess(`Deleted "${skill.name}"`);
      setTimeout(() => setSuccess(null), 4000);
      await fetchSkills();
    } catch (err) {
      const detail = err.response?.data?.detail || 'Failed to delete skill';
      setError(detail);
      setTimeout(() => setError(null), 5000);
    } finally {
      setActionLoading(null);
    }
  };

  const renderSkillCard = (skill) => {
    const isLoading = actionLoading === skill.id;

    return (
      <Col md={6} lg={4} key={skill.id} className="mb-3">
        <Card
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: 12,
            background: 'var(--surface-elevated)',
            transition: 'all 0.2s ease',
            boxShadow: '0 2px 10px rgba(100, 130, 170, 0.08)',
            height: '100%',
          }}
        >
          <Card.Body style={{ padding: '1rem 1.25rem' }}>
            <div className="d-flex align-items-start justify-content-between mb-2">
              <div className="d-flex align-items-center gap-2">
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    background: 'rgba(100, 130, 170, 0.12)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--color-foreground-muted)',
                    flexShrink: 0,
                  }}
                >
                  <FaCog size={16} />
                </div>
                <div>
                  <div
                    className="fw-semibold"
                    style={{ color: 'var(--color-foreground)', fontSize: '0.95rem' }}
                  >
                    {skill.name}
                  </div>
                </div>
              </div>
              <div className="d-flex align-items-center gap-1 flex-shrink-0">
                {skill.is_system && (
                  <Badge
                    bg="info"
                    style={{ fontSize: '0.65rem', fontWeight: 500 }}
                  >
                    <FaStar size={8} className="me-1" />
                    System
                  </Badge>
                )}
                <Badge
                  bg="secondary"
                  style={{ fontSize: '0.65rem', fontWeight: 500 }}
                >
                  {skill.skill_type || 'other'}
                </Badge>
                {skill.enabled !== undefined && (
                  <Badge
                    bg={skill.enabled ? 'success' : 'warning'}
                    style={{ fontSize: '0.65rem', fontWeight: 500 }}
                  >
                    {skill.enabled ? 'Enabled' : 'Disabled'}
                  </Badge>
                )}
              </div>
            </div>

            {skill.description && (
              <p
                className="mb-3"
                style={{
                  fontSize: '0.82rem',
                  color: 'var(--color-foreground-muted)',
                  lineHeight: 1.4,
                  marginTop: 4,
                }}
              >
                {skill.description}
              </p>
            )}

            <div className="d-flex gap-2 mt-auto">
              {skill.is_system ? (
                <Button
                  variant="outline-primary"
                  size="sm"
                  onClick={() => handleCloneSkill(skill)}
                  disabled={isLoading}
                  style={{ fontSize: '0.78rem' }}
                >
                  {isLoading ? (
                    <Spinner
                      animation="border"
                      size="sm"
                      style={{ width: 12, height: 12, borderWidth: 1.5 }}
                      className="me-1"
                    />
                  ) : (
                    <FaCopy className="me-1" size={10} />
                  )}
                  Clone
                </Button>
              ) : (
                <Button
                  variant="outline-danger"
                  size="sm"
                  onClick={() => handleDeleteSkill(skill)}
                  disabled={isLoading}
                  style={{ fontSize: '0.78rem' }}
                >
                  {isLoading ? (
                    <Spinner
                      animation="border"
                      size="sm"
                      style={{ width: 12, height: 12, borderWidth: 1.5 }}
                      className="me-1"
                    />
                  ) : (
                    <FaTrash className="me-1" size={10} />
                  )}
                  Delete
                </Button>
              )}
            </div>
          </Card.Body>
        </Card>
      </Col>
    );
  };

  return (
    <Card
      className="mb-4"
      style={{
        border: '1px solid var(--color-border)',
        borderRadius: 12,
        background: 'var(--surface-elevated)',
        boxShadow: '0 2px 15px rgba(100, 130, 170, 0.08)',
      }}
    >
      <Card.Header
        style={{
          background: 'transparent',
          borderBottom: '1px solid var(--color-border)',
          padding: '0.75rem 1.25rem',
        }}
      >
        <div className="d-flex align-items-center justify-content-between">
          <h6
            className="mb-0 d-flex align-items-center"
            style={{ color: 'var(--color-foreground)' }}
          >
            <FaCog className="me-2" />
            Skills
            <Badge
              bg="secondary"
              className="ms-2"
              style={{ fontSize: '0.68rem', fontWeight: 500 }}
            >
              {skills.length}
            </Badge>
          </h6>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowCreateForm(!showCreateForm)}
            style={{ fontSize: '0.82rem' }}
          >
            <FaPlus className="me-1" size={10} />
            Create Skill
          </Button>
        </div>
      </Card.Header>
      <Card.Body>
        {error && (
          <Alert
            variant="danger"
            onClose={() => setError(null)}
            dismissible
            className="mb-3"
            style={{ fontSize: '0.85rem' }}
          >
            {error}
          </Alert>
        )}
        {success && (
          <Alert
            variant="success"
            onClose={() => setSuccess(null)}
            dismissible
            className="mb-3"
            style={{ fontSize: '0.85rem' }}
          >
            {success}
          </Alert>
        )}

        {/* Create Skill Form */}
        {showCreateForm && (
          <Card
            className="mb-4"
            style={{
              border: '1px solid var(--color-border)',
              borderRadius: 10,
              background: 'rgba(100, 130, 170, 0.05)',
            }}
          >
            <Card.Body style={{ padding: '1rem 1.25rem' }}>
              <h6
                className="mb-3"
                style={{ color: 'var(--color-foreground)', fontSize: '0.9rem' }}
              >
                New Skill
              </h6>
              <Form onSubmit={handleCreateSkill}>
                <Row>
                  <Col md={6}>
                    <Form.Group className="mb-2">
                      <Form.Label style={{ fontSize: '0.8rem', color: 'var(--color-foreground-muted)' }}>
                        Name <span className="text-danger">*</span>
                      </Form.Label>
                      <Form.Control
                        size="sm"
                        type="text"
                        placeholder="e.g. my_scoring_skill"
                        value={newSkill.name}
                        onChange={(e) => setNewSkill({ ...newSkill, name: e.target.value })}
                        style={{
                          background: 'var(--surface-contrast, rgba(0,0,0,0.2))',
                          border: '1px solid var(--color-border)',
                          color: 'var(--color-foreground)',
                          fontSize: '0.82rem',
                        }}
                      />
                    </Form.Group>
                  </Col>
                  <Col md={6}>
                    <Form.Group className="mb-2">
                      <Form.Label style={{ fontSize: '0.8rem', color: 'var(--color-foreground-muted)' }}>
                        Skill Type
                      </Form.Label>
                      <Form.Select
                        size="sm"
                        value={newSkill.skill_type}
                        onChange={(e) => setNewSkill({ ...newSkill, skill_type: e.target.value })}
                        style={{
                          background: 'var(--surface-contrast, rgba(0,0,0,0.2))',
                          border: '1px solid var(--color-border)',
                          color: 'var(--color-foreground)',
                          fontSize: '0.82rem',
                        }}
                      >
                        <option value="scoring">Scoring</option>
                      </Form.Select>
                    </Form.Group>
                  </Col>
                </Row>
                <Form.Group className="mb-2">
                  <Form.Label style={{ fontSize: '0.8rem', color: 'var(--color-foreground-muted)' }}>
                    Description
                  </Form.Label>
                  <Form.Control
                    size="sm"
                    type="text"
                    placeholder="Brief description of the skill"
                    value={newSkill.description}
                    onChange={(e) => setNewSkill({ ...newSkill, description: e.target.value })}
                    style={{
                      background: 'var(--surface-contrast, rgba(0,0,0,0.2))',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-foreground)',
                      fontSize: '0.82rem',
                    }}
                  />
                </Form.Group>
                <Form.Group className="mb-3">
                  <Form.Label style={{ fontSize: '0.8rem', color: 'var(--color-foreground-muted)' }}>
                    Config (JSON)
                  </Form.Label>
                  <Form.Control
                    as="textarea"
                    rows={3}
                    size="sm"
                    placeholder='{"key": "value"}'
                    value={newSkill.config}
                    onChange={(e) => setNewSkill({ ...newSkill, config: e.target.value })}
                    style={{
                      background: 'var(--surface-contrast, rgba(0,0,0,0.2))',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-foreground)',
                      fontSize: '0.82rem',
                      fontFamily: 'monospace',
                    }}
                  />
                </Form.Group>
                <div className="d-flex gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    type="submit"
                    disabled={creating}
                    style={{ fontSize: '0.82rem' }}
                  >
                    {creating ? (
                      <Spinner
                        animation="border"
                        size="sm"
                        style={{ width: 14, height: 14, borderWidth: 1.5 }}
                        className="me-1"
                      />
                    ) : (
                      <FaPlus className="me-1" size={10} />
                    )}
                    Create
                  </Button>
                  <Button
                    variant="outline-secondary"
                    size="sm"
                    onClick={() => setShowCreateForm(false)}
                    style={{ fontSize: '0.82rem' }}
                  >
                    Cancel
                  </Button>
                </div>
              </Form>
            </Card.Body>
          </Card>
        )}

        {/* Skills List */}
        {loading ? (
          <div className="text-center py-4">
            <Spinner animation="border" size="sm" variant="primary" />
            <p className="text-muted mt-2 mb-0" style={{ fontSize: '0.85rem' }}>
              Loading skills...
            </p>
          </div>
        ) : skills.length === 0 ? (
          <div className="text-center py-4">
            <FaCog size={32} className="text-muted mb-2" />
            <p className="text-muted mb-0" style={{ fontSize: '0.85rem' }}>
              No skills configured yet
            </p>
          </div>
        ) : (
          Object.entries(groupedSkills).map(([type, typeSkills]) => (
            <div key={type} className="mb-4">
              <h6
                className="text-uppercase mb-3"
                style={{
                  fontSize: '0.75rem',
                  letterSpacing: '0.5px',
                  color: 'var(--color-foreground-muted)',
                  fontWeight: 600,
                }}
              >
                {type}
              </h6>
              <Row>{typeSkills.map(renderSkillCard)}</Row>
            </div>
          ))
        )}
      </Card.Body>
    </Card>
  );
};

export default SkillsManagementPanel;
