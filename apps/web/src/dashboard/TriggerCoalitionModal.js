/*
 * TriggerCoalitionModal — kicks off an A2A coalition run against the
 * active chat session.
 *
 * Calls POST /api/v1/collaborations/trigger with a user-supplied task
 * description + a chosen CollaborationPattern. The backend dispatches
 * the CoalitionWorkflow; resulting `collaboration_started`,
 * `phase_started`, `agent_response`, etc. events stream into the
 * already-mounted AgentActivityPanel via the shared v2 SSE.
 */
import { useState } from 'react';
import { Modal } from 'react-bootstrap';
import api from '../services/api';
import './TriggerCoalitionModal.css';

const PATTERNS = [
  { value: 'propose_critique_revise', label: 'Propose · Critique · Revise', hint: '3 agents iterate on a draft' },
  { value: 'plan_verify', label: 'Plan · Verify', hint: 'Planner → verifier' },
  { value: 'research_synthesize', label: 'Research · Synthesize', hint: 'Researcher → synthesizer' },
  { value: 'debate_resolve', label: 'Debate · Resolve', hint: 'Two agents debate, third resolves' },
  { value: 'incident_investigation', label: 'Incident Investigation', hint: 'Triage → investigate → resolve' },
];

const TriggerCoalitionModal = ({ open, onClose, sessionId, onDispatched }) => {
  const [task, setTask] = useState('');
  const [pattern, setPattern] = useState('propose_critique_revise');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const reset = () => { setTask(''); setError(null); setBusy(false); };

  const handleClose = () => { reset(); onClose(); };

  const handleDispatch = async () => {
    if (!task.trim() || !sessionId || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.post('/collaborations/trigger', {
        chat_session_id: sessionId,
        task_description: task.trim(),
        pattern,
      });
      onDispatched?.({ pattern, task: task.trim() });
      reset();
      onClose();
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Trigger failed');
      setBusy(false);
    }
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleDispatch();
    }
  };

  return (
    <Modal show={open} onHide={handleClose} centered className="tcm-modal" backdropClassName="tcm-backdrop">
      <div className="tcm-body">
        <div className="tcm-header">
          <span className="tcm-title">Run agent coalition</span>
          <span className="tcm-sub">Dispatches an A2A workflow against the active session.</span>
        </div>

        <label className="tcm-label" htmlFor="tcm-task">Task description</label>
        <textarea
          id="tcm-task"
          className="tcm-textarea"
          rows={4}
          autoFocus
          placeholder="e.g. Draft a launch email for the new dashboard, then critique and revise it."
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={handleKey}
          disabled={busy}
        />

        <label className="tcm-label" htmlFor="tcm-pattern">Pattern</label>
        <select
          id="tcm-pattern"
          className="tcm-select"
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
          disabled={busy}
        >
          {PATTERNS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
        <p className="tcm-hint">{PATTERNS.find((p) => p.value === pattern)?.hint}</p>

        {!sessionId && (
          <div className="tcm-warning">Pick an active session in the sidebar first.</div>
        )}
        {error && <div className="tcm-error">{error}</div>}

        <div className="tcm-actions">
          <button type="button" className="ap-btn-secondary ap-btn-sm" onClick={handleClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="ap-btn-primary ap-btn-sm"
            onClick={handleDispatch}
            disabled={!task.trim() || !sessionId || busy}
          >
            {busy ? 'Dispatching…' : 'Dispatch  ⌘↵'}
          </button>
        </div>
      </div>
    </Modal>
  );
};

export default TriggerCoalitionModal;
