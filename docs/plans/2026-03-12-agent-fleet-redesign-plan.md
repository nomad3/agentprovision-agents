# Agent Fleet Page Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the flat agent table with a dashboard-like card grid and add a dedicated agent detail page with tabbed profile view (Overview, Relations, Tasks, Config).

**Architecture:** Two new/rewritten pages. AgentsPage becomes a card grid where each card shows agent summary with skills, stats, and relations. Clicking navigates to AgentDetailPage — a new page at `/agents/:id` with a persistent header and four tabs. Quick Create modal removed entirely; Agent Wizard is the sole creation path.

**Tech Stack:** React 18, React Bootstrap (Card, Badge, Nav, Spinner, Row, Col), React Router v7 (useParams, useNavigate, Link), existing `/api/v1/agents`, `/api/v1/tasks` endpoints.

---

## Task 1: Add agent skills to API response schema

**Files:**
- Modify: `apps/api/app/schemas/agent.py`

**Step 1: Add skills field to Agent response schema**

In `apps/api/app/schemas/agent.py`, import the AgentSkill schema and add a `skills` field:

```python
from pydantic import BaseModel
from typing import Optional, List
import uuid

from app.schemas.agent_skill import AgentSkill as AgentSkillSchema


class AgentBase(BaseModel):
    name: str
    description: str | None = None
    config: dict | None = None
    # Orchestration fields
    role: str | None = None  # "analyst", "manager", "specialist"
    capabilities: list[str] | None = None  # list of capability strings
    personality: dict | None = None  # dict with tone, verbosity settings
    autonomy_level: str = "supervised"  # "full", "supervised", "approval_required"
    max_delegation_depth: int = 2

class AgentCreate(AgentBase):
    pass

class AgentUpdate(AgentBase):
    pass

class Agent(AgentBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    skills: List[AgentSkillSchema] = []

    class Config:
        from_attributes = True
```

The SQLAlchemy model already has `skills = relationship("AgentSkill", ...)` and Pydantic's `from_attributes = True` will auto-serialize it.

**Step 2: Verify**

Run: `cd apps/api && python -c "from app.schemas.agent import Agent; print('OK')"`
Expected: OK

**Step 3: Commit**

```bash
git add apps/api/app/schemas/agent.py
git commit -m "feat: include agent skills in API response schema"
```

---

## Task 2: Add task/group fetch helpers to agent service

**Files:**
- Modify: `apps/web/src/services/agent.js`

**Step 1: Add helper methods**

Replace the entire file:

```javascript
import api from './api';

const agentService = {
  getAll: () => api.get('/agents/'),

  getById: (id) => api.get(`/agents/${id}`),

  create: (data) => api.post('/agents/', data),

  update: (id, data) => api.put(`/agents/${id}`, data),

  delete: (id) => api.delete(`/agents/${id}`),

  deploy: (id, deploymentData) => api.post(`/agents/${id}/deploy`, deploymentData),

  // Tasks for a specific agent (filter client-side)
  getTasks: (params = {}) => api.get('/tasks', { params }),

  // Agent groups
  getGroups: () => api.get('/agent_groups/'),
};

export default agentService;
```

**Step 2: Commit**

```bash
git add apps/web/src/services/agent.js
git commit -m "feat: add task and group fetch helpers to agent service"
```

---

## Task 3: Rewrite AgentsPage as card grid

**Files:**
- Rewrite: `apps/web/src/pages/AgentsPage.js`

**Step 1: Rewrite the entire file**

Replace `apps/web/src/pages/AgentsPage.js` with:

```jsx
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
    // Merge config.skills/tools + AgentSkill records
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
```

**Step 2: Commit**

```bash
git add apps/web/src/pages/AgentsPage.js
git commit -m "feat: rewrite Agent Fleet page as dashboard card grid, remove Quick Create"
```

---

## Task 4: Add `/agents/:id` route to App.js

**Files:**
- Modify: `apps/web/src/App.js`

**Step 1: Import AgentDetailPage**

After line 8 (`import AgentsPage`), add:

```javascript
import AgentDetailPage from './pages/AgentDetailPage';
```

**Step 2: Add route**

After line 75 (the `/agents` route), add:

```jsx
<Route path="/agents/:id" element={<ProtectedRoute><AgentDetailPage /></ProtectedRoute>} />
```

Make sure it comes AFTER `/agents/wizard` (line 76) so the wizard route matches first.

**Step 3: Commit**

```bash
git add apps/web/src/App.js
git commit -m "feat: add /agents/:id route for agent detail page"
```

---

## Task 5: Create AgentDetailPage — Overview tab

**Files:**
- Create: `apps/web/src/pages/AgentDetailPage.js`
- Create: `apps/web/src/pages/AgentDetailPage.css`

**Step 1: Create the CSS file**

Create `apps/web/src/pages/AgentDetailPage.css`:

```css
.agent-detail-page .detail-header {
  margin-bottom: 24px;
}

.agent-detail-page .tab-nav {
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 24px;
}

.agent-detail-page .tab-nav .nav-link {
  color: var(--color-muted);
  border: none;
  padding: 8px 16px;
  font-size: 0.82rem;
  font-weight: 500;
  background: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
}

.agent-detail-page .tab-nav .nav-link.active {
  color: var(--color-foreground);
  border-bottom-color: #4dabf7;
  background: none;
}

.agent-detail-page .tab-nav .nav-link:hover:not(.active) {
  color: var(--color-foreground);
}

.agent-detail-page .stat-tile {
  background: var(--surface-elevated);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 16px 20px;
}

.agent-detail-page .stat-tile .stat-value {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--color-foreground);
  line-height: 1.2;
}

.agent-detail-page .stat-tile .stat-label {
  font-size: 0.72rem;
  color: var(--color-muted);
  margin-top: 4px;
}

.agent-detail-page .skill-card {
  background: var(--surface-elevated);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 14px 18px;
}

.agent-detail-page .proficiency-bar {
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.08);
  overflow: hidden;
}

.agent-detail-page .proficiency-bar .fill {
  height: 100%;
  border-radius: 3px;
  background: #4dabf7;
  transition: width 0.3s ease;
}

.agent-detail-page .config-block {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 16px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
  color: var(--color-muted);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
}

.agent-detail-page .relation-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--color-border);
  font-size: 0.82rem;
}

.agent-detail-page .relation-row:last-child {
  border-bottom: none;
}

.agent-detail-page .task-table {
  width: 100%;
  font-size: 0.78rem;
}

.agent-detail-page .task-table th {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--color-muted);
  padding: 8px 0;
  border-bottom: 1px solid var(--color-border);
}

.agent-detail-page .task-table td {
  padding: 10px 0;
  color: var(--color-foreground);
  border-bottom: 1px solid var(--color-border);
}
```

**Step 2: Create the component**

Create `apps/web/src/pages/AgentDetailPage.js`:

```jsx
import { useEffect, useState } from 'react';
import { Badge, Button, Col, Modal, Nav, Row, Spinner } from 'react-bootstrap';
import { useNavigate, useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import agentService from '../services/agent';
import './AgentDetailPage.css';

const STATUS_COLORS = { active: '#22c55e', error: '#ef4444', inactive: '#94a3b8' };
const ROLE_COLORS = { analyst: '#6f42c1', manager: '#0d6efd', specialist: '#fd7e14' };
const TASK_STATUS_COLORS = {
  completed: '#22c55e', failed: '#ef4444', executing: '#f59e0b',
  thinking: '#f59e0b', queued: '#94a3b8', delegated: '#6f42c1',
};
const PRIORITY_COLORS = { critical: '#ef4444', high: '#f59e0b', normal: '#4dabf7', low: '#94a3b8' };

const AgentDetailPage = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const [agent, setAgent] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      agentService.getById(id).then(r => setAgent(r.data)),
      agentService.getTasks().then(r => setTasks((r.data || []).filter(t => t.assigned_agent_id === id))).catch(() => {}),
      agentService.getAll().then(r => setAgents(r.data || [])).catch(() => {}),
    ])
      .catch(err => console.error('Failed to load agent:', err))
      .finally(() => setLoading(false));
  }, [id]);

  const handleDelete = async () => {
    try {
      setDeleting(true);
      await agentService.delete(id);
      navigate('/agents');
    } catch (err) {
      console.error(err);
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="text-center py-5">
          <Spinner animation="border" size="sm" variant="primary" />
        </div>
      </Layout>
    );
  }

  if (!agent) {
    return (
      <Layout>
        <div className="text-center py-5">
          <p style={{ color: 'var(--color-muted)' }}>Agent not found.</p>
          <Button variant="outline-secondary" size="sm" onClick={() => navigate('/agents')}>Back to Fleet</Button>
        </div>
      </Layout>
    );
  }

  // Merge skills from config and AgentSkill records
  const configSkills = agent.config?.skills || agent.config?.tools || [];
  const agentSkillRecords = agent.skills || [];
  const skillMap = {};
  agentSkillRecords.forEach(s => { skillMap[s.skill_name] = s; });
  configSkills.forEach(s => { if (!skillMap[s]) skillMap[s] = { skill_name: s, proficiency: null, times_used: 0, success_rate: 0 }; });
  const allSkills = Object.values(skillMap);

  // Task stats
  const completedTasks = tasks.filter(t => t.status === 'completed').length;
  const totalTasks = tasks.length;
  const successRate = totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0;
  const totalTokens = tasks.reduce((sum, t) => sum + (t.tokens_used || 0), 0);
  const activeTasks = tasks.filter(t => ['queued', 'thinking', 'executing'].includes(t.status)).length;

  const status = agent.status || 'inactive';

  return (
    <Layout>
      <div className="agent-detail-page" style={{ maxWidth: 1100 }}>
        {/* Header */}
        <div className="detail-header">
          <button
            onClick={() => navigate('/agents')}
            style={{ background: 'none', border: 'none', color: 'var(--color-muted)', cursor: 'pointer', fontSize: '0.82rem', padding: 0, marginBottom: 12 }}
          >
            ← Back to Agent Fleet
          </button>

          <div className="d-flex justify-content-between align-items-start">
            <div>
              <div className="d-flex align-items-center gap-2 mb-1">
                <span style={{ width: 10, height: 10, borderRadius: '50%', background: STATUS_COLORS[status] || '#94a3b8' }} />
                <h4 style={{ fontWeight: 600, margin: 0, color: 'var(--color-foreground)' }}>{agent.name}</h4>
              </div>
              <p style={{ fontSize: '0.85rem', color: 'var(--color-muted)', margin: '4px 0 8px 0' }}>
                {agent.description || 'No description'}
              </p>
              <div className="d-flex gap-2 flex-wrap">
                <Badge bg="none" style={{ fontSize: '0.7rem', backgroundColor: 'var(--surface-contrast, rgba(255,255,255,0.06))', color: 'var(--color-muted)' }}>
                  {agent.config?.model || 'gpt-4'}
                </Badge>
                {agent.role && (
                  <Badge bg="none" style={{ fontSize: '0.7rem', backgroundColor: ROLE_COLORS[agent.role] || '#6c757d' }}>
                    {agent.role}
                  </Badge>
                )}
                <Badge bg="none" style={{ fontSize: '0.7rem', backgroundColor: 'rgba(255,255,255,0.1)', color: 'var(--color-muted)' }}>
                  {agent.autonomy_level || 'supervised'}
                </Badge>
              </div>
            </div>
            <div className="d-flex gap-2">
              <Button variant="outline-danger" size="sm" onClick={() => setDeleteConfirm(true)} style={{ fontSize: '0.78rem' }}>
                Delete
              </Button>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <Nav className="tab-nav" as="ul">
          {['overview', 'relations', 'tasks', 'config'].map(tab => (
            <Nav.Item as="li" key={tab}>
              <Nav.Link
                className={activeTab === tab ? 'active' : ''}
                onClick={() => setActiveTab(tab)}
                style={{ textTransform: 'capitalize' }}
              >
                {tab}
              </Nav.Link>
            </Nav.Item>
          ))}
        </Nav>

        {/* Tab Content */}
        {activeTab === 'overview' && (
          <div>
            {/* Stats */}
            <Row className="g-3 mb-4">
              {[
                { label: 'Total Tasks', value: totalTasks },
                { label: 'Completed', value: completedTasks },
                { label: 'Active', value: activeTasks },
                { label: 'Success Rate', value: `${successRate}%` },
              ].map(s => (
                <Col md={3} sm={6} key={s.label}>
                  <div className="stat-tile">
                    <div className="stat-value">{s.value}</div>
                    <div className="stat-label">{s.label}</div>
                  </div>
                </Col>
              ))}
            </Row>

            {/* Skills */}
            <div style={{ fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--color-muted)', marginBottom: 12 }}>
              Skills ({allSkills.length})
            </div>
            {allSkills.length === 0 ? (
              <p style={{ fontSize: '0.82rem', color: 'var(--color-muted)' }}>No skills configured.</p>
            ) : (
              <Row className="g-2 mb-4">
                {allSkills.map(skill => (
                  <Col md={6} lg={4} key={skill.skill_name}>
                    <div className="skill-card">
                      <div className="d-flex justify-content-between align-items-center mb-1">
                        <span style={{ fontSize: '0.85rem', fontWeight: 500, color: 'var(--color-foreground)' }}>
                          {skill.skill_name.replace(/_/g, ' ')}
                        </span>
                        {skill.learned_from && (
                          <span style={{ fontSize: '0.65rem', padding: '1px 5px', borderRadius: 3, background: 'rgba(255,255,255,0.06)', color: 'var(--color-muted)' }}>
                            {skill.learned_from}
                          </span>
                        )}
                      </div>
                      {skill.proficiency !== null && skill.proficiency !== undefined && (
                        <div className="d-flex align-items-center gap-2 mb-1">
                          <div className="proficiency-bar" style={{ flex: 1 }}>
                            <div className="fill" style={{ width: `${Math.round(skill.proficiency * 100)}%` }} />
                          </div>
                          <span style={{ fontSize: '0.68rem', color: 'var(--color-muted)', minWidth: 28 }}>
                            {Math.round(skill.proficiency * 100)}%
                          </span>
                        </div>
                      )}
                      <div className="d-flex gap-3" style={{ fontSize: '0.68rem', color: 'var(--color-muted)' }}>
                        <span>Used {skill.times_used || 0}x</span>
                        {skill.success_rate > 0 && <span>Success {Math.round(skill.success_rate * 100)}%</span>}
                      </div>
                    </div>
                  </Col>
                ))}
              </Row>
            )}
          </div>
        )}

        {activeTab === 'relations' && (
          <div>
            <div style={{ background: 'var(--surface-elevated)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '20px 24px' }}>
              {agents.filter(a => a.id !== agent.id).length === 0 ? (
                <p style={{ fontSize: '0.82rem', color: 'var(--color-muted)', margin: 0 }}>No other agents in the fleet.</p>
              ) : (
                agents.filter(a => a.id !== agent.id).map(other => (
                  <div key={other.id} className="relation-row">
                    <span style={{ color: 'var(--color-muted)' }}>↔</span>
                    <span
                      style={{ color: '#4dabf7', cursor: 'pointer', fontWeight: 500 }}
                      onClick={() => navigate(`/agents/${other.id}`)}
                    >
                      {other.name}
                    </span>
                    <Badge bg="none" style={{ fontSize: '0.65rem', backgroundColor: 'rgba(255,255,255,0.08)', color: 'var(--color-muted)' }}>
                      {other.role || 'agent'}
                    </Badge>
                    <span style={{ fontSize: '0.72rem', color: 'var(--color-muted)', marginLeft: 'auto' }}>
                      {other.status || 'inactive'}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {activeTab === 'tasks' && (
          <div style={{ background: 'var(--surface-elevated)', border: '1px solid var(--color-border)', borderRadius: 8, padding: '20px 24px' }}>
            {tasks.length === 0 ? (
              <p style={{ fontSize: '0.82rem', color: 'var(--color-muted)', margin: 0 }}>No tasks assigned to this agent.</p>
            ) : (
              <table className="task-table">
                <thead>
                  <tr>
                    <th>Objective</th>
                    <th>Status</th>
                    <th>Priority</th>
                    <th>Created</th>
                    <th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {tasks.map(task => (
                    <tr key={task.id}>
                      <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {task.objective}
                      </td>
                      <td>
                        <Badge bg="none" style={{ fontSize: '0.65rem', backgroundColor: TASK_STATUS_COLORS[task.status] || '#94a3b8' }}>
                          {task.status}
                        </Badge>
                      </td>
                      <td>
                        <Badge bg="none" style={{ fontSize: '0.65rem', backgroundColor: PRIORITY_COLORS[task.priority] || '#94a3b8' }}>
                          {task.priority || 'normal'}
                        </Badge>
                      </td>
                      <td style={{ color: 'var(--color-muted)' }}>
                        {task.created_at ? new Date(task.created_at).toLocaleDateString() : '—'}
                      </td>
                      <td style={{ color: 'var(--color-muted)' }}>
                        {task.confidence != null ? `${Math.round(task.confidence * 100)}%` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {activeTab === 'config' && (
          <div>
            {/* System Prompt */}
            {(agent.config?.system_prompt || agent.system_prompt) && (
              <div className="mb-4">
                <div style={{ fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--color-muted)', marginBottom: 8 }}>
                  System Prompt
                </div>
                <div className="config-block">
                  {agent.config?.system_prompt || agent.system_prompt}
                </div>
              </div>
            )}

            {/* Parameters */}
            <div style={{ fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--color-muted)', marginBottom: 8 }}>
              Parameters
            </div>
            <Row className="g-3 mb-4">
              {[
                { label: 'Model', value: agent.config?.model || 'gpt-4' },
                { label: 'Temperature', value: agent.config?.temperature ?? 0.7 },
                { label: 'Max Tokens', value: agent.config?.max_tokens ?? 2000 },
                { label: 'Autonomy', value: agent.autonomy_level || 'supervised' },
              ].map(p => (
                <Col md={3} sm={6} key={p.label}>
                  <div className="stat-tile">
                    <div className="stat-label">{p.label}</div>
                    <div style={{ fontSize: '1rem', fontWeight: 600, color: 'var(--color-foreground)', marginTop: 4 }}>
                      {p.value}
                    </div>
                  </div>
                </Col>
              ))}
            </Row>

            {/* Raw Config */}
            <div style={{ fontSize: '0.7rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', color: 'var(--color-muted)', marginBottom: 8 }}>
              Raw Configuration
            </div>
            <div className="config-block">
              {JSON.stringify(agent.config || {}, null, 2)}
            </div>
          </div>
        )}
      </div>

      {/* Delete Modal */}
      <Modal show={deleteConfirm} onHide={() => setDeleteConfirm(false)} centered size="sm">
        <Modal.Body className="text-center py-4">
          <p style={{ fontSize: '0.88rem', fontWeight: 500, marginBottom: 8 }}>
            Delete "{agent.name}"?
          </p>
          <p style={{ fontSize: '0.78rem', color: 'var(--color-muted)', marginBottom: 20 }}>
            This action cannot be undone.
          </p>
          <div className="d-flex justify-content-center gap-2">
            <Button variant="outline-secondary" size="sm" onClick={() => setDeleteConfirm(false)}>Cancel</Button>
            <Button variant="danger" size="sm" onClick={handleDelete} disabled={deleting}>
              {deleting ? 'Deleting...' : 'Delete'}
            </Button>
          </div>
        </Modal.Body>
      </Modal>
    </Layout>
  );
};

export default AgentDetailPage;
```

**Step 3: Commit**

```bash
git add apps/web/src/pages/AgentDetailPage.js apps/web/src/pages/AgentDetailPage.css
git commit -m "feat: add agent detail page with Overview, Relations, Tasks, Config tabs"
```
