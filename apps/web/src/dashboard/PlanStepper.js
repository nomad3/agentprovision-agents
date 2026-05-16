/*
 * PlanStepper — Phase 2 inline plan progress.
 *
 * Subscribes to the v2 SSE stream and reduces `plan_step_changed`
 * events into a per-plan state machine. Renders the most recent
 * in-flight plan as a horizontal stepper at the top of the chat.
 *
 * Each event payload (per design doc §5):
 *   { plan_id, step_index, label, status }
 * where status ∈ 'pending' | 'running' | 'complete' | 'failed' | 'skipped'.
 *
 * If the orchestrator emits multiple events for the same step_index,
 * the latest status wins. A `plan_id` change starts a fresh plan
 * (previous plan stays visible for 5 s as a "done" indicator).
 *
 * Hidden entirely when there's no plan activity in the active session.
 */
import { useEffect, useMemo, useState } from 'react';
import { FaCheck, FaTimes, FaForward, FaCircle } from 'react-icons/fa';
import { useV2SessionEvents } from './hooks/useV2SessionEvents';
import './PlanStepper.css';

const STATUS_ICONS = {
  pending: { Icon: FaCircle, cls: 'pending' },
  running: { Icon: FaCircle, cls: 'running' },
  complete: { Icon: FaCheck, cls: 'complete' },
  failed: { Icon: FaTimes, cls: 'failed' },
  skipped: { Icon: FaForward, cls: 'skipped' },
};

const PLAN_LINGER_MS = 5000;

const PlanStepper = ({ sessionId }) => {
  const { events } = useV2SessionEvents(sessionId);
  const [hideAfter, setHideAfter] = useState(null);

  const plan = useMemo(() => {
    // Reduce the event stream into the most recent plan's step map.
    let planId = null;
    const stepsByIndex = new Map();
    for (const env of events) {
      const t = env.type || env.event_type;
      if (t !== 'plan_step_changed') continue;
      const p = env.payload || {};
      // A new plan_id resets the per-plan state.
      if (p.plan_id && p.plan_id !== planId) {
        planId = p.plan_id;
        stepsByIndex.clear();
      }
      const idx = p.step_index != null ? Number(p.step_index) : null;
      if (idx == null) continue;
      stepsByIndex.set(idx, {
        index: idx,
        label: p.label || `Step ${idx + 1}`,
        status: p.status || 'pending',
      });
    }
    if (stepsByIndex.size === 0) return null;
    const steps = Array.from(stepsByIndex.values()).sort((a, b) => a.index - b.index);
    return { planId, steps };
  }, [events]);

  // Linger logic — when every step is in a terminal status, set a 5s
  // timer to hide the stepper. Cleared if a new step starts.
  useEffect(() => {
    if (!plan) { setHideAfter(null); return undefined; }
    const allTerminal = plan.steps.every((s) => ['complete', 'failed', 'skipped'].includes(s.status));
    if (!allTerminal) { setHideAfter(null); return undefined; }
    const t = setTimeout(() => setHideAfter(Date.now()), PLAN_LINGER_MS);
    return () => clearTimeout(t);
  }, [plan]);

  if (!plan) return null;
  if (hideAfter) return null;

  const total = plan.steps.length;
  const done = plan.steps.filter((s) => s.status === 'complete').length;

  return (
    <div className="ap-plan-stepper" role="status" aria-label="Plan progress">
      <div className="ap-plan-stepper-header">
        <span className="ap-plan-stepper-title">Plan</span>
        <span className="ap-plan-stepper-progress">{done} / {total}</span>
      </div>
      <ol className="ap-plan-stepper-steps">
        {plan.steps.map((step, idx) => {
          const { Icon, cls } = STATUS_ICONS[step.status] || STATUS_ICONS.pending;
          return (
            <li key={step.index} className={`ap-plan-stepper-step ${cls}`}>
              <span className="ap-plan-stepper-step-marker">
                <Icon size={8} />
              </span>
              <span className="ap-plan-stepper-step-label" title={step.label}>
                {step.label}
              </span>
              {idx < plan.steps.length - 1 && <span className="ap-plan-stepper-connector" aria-hidden="true" />}
            </li>
          );
        })}
      </ol>
    </div>
  );
};

export default PlanStepper;
