/**
 * /onboarding — guided initial-training wizard for new tenants.
 *
 * Mirrors the CLI `alpha quickstart` flow (apps/agentprovision-cli/src/
 * commands/quickstart.rs) as React screens so a user signing up via
 * the web hits the same memory-seeding contract.
 *
 * Stages (single-file state machine — small enough to not warrant a
 * separate routing tree; each stage is a sub-component below):
 *
 *   welcome  → explainer + Skip / Get started
 *   channel  → wedge picker (mirrors WEDGES from services/onboarding.js)
 *   training → polls /memory/training/{run_id} until terminal
 *   done     → "go to chat" CTA + onboarding stamped complete
 *
 * Idempotency: snapshot_id is generated once when the user picks a
 * channel and stashed in sessionStorage so a tab refresh mid-training
 * re-POSTs the same UUID and the server returns the existing row
 * (deduplicated=true) instead of spawning a parallel workflow. Same
 * pattern as `~/.config/agentprovision/quickstart-{tenant_id}.toml`
 * on the CLI side.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Badge, Button, Card, Container, ProgressBar, Spinner } from 'react-bootstrap';
import { useNavigate } from 'react-router-dom';

import {
  bulkIngestTraining,
  completeOnboarding,
  deferOnboarding,
  getOnboardingStatus,
  getTrainingRun,
  WEDGES,
} from '../services/onboarding';

const SESSION_KEY = 'agentprovision.onboarding.snapshot_id';

const OnboardingPage = () => {
  const navigate = useNavigate();
  const [stage, setStage] = useState('loading');  // loading | welcome | channel | training | done
  const [error, setError] = useState(null);
  const [selectedWedge, setSelectedWedge] = useState(null);
  const [training, setTraining] = useState(null);  // { runId, status, items_total, items_processed, error }

  // (1) Status check on mount. Already-onboarded tenants hitting this
  // URL directly get a friendly redirect rather than re-running.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await getOnboardingStatus();
        if (cancelled) return;
        if (status.onboarded) {
          navigate('/dashboard', { replace: true });
          return;
        }
        setStage('welcome');
      } catch (e) {
        if (!cancelled) {
          // A failed status probe means the user can still proceed —
          // worst case the final /onboarding/complete will surface
          // the same error then. Don't block the wizard on the probe.
          // eslint-disable-next-line no-console
          console.warn('onboarding status probe failed:', e);
          setStage('welcome');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  const handleSkip = useCallback(async () => {
    try {
      await deferOnboarding();
    } catch (e) {
      // Best-effort — same semantic as the CLI's auto-trigger skip
      // (let _ = ctx.client.defer_onboarding().await). Worst case
      // the user gets the prompt again next dashboard mount; we
      // don't want to block them on this.
      // eslint-disable-next-line no-console
      console.warn('defer call failed:', e);
    }
    navigate('/dashboard', { replace: true });
  }, [navigate]);

  const handlePickWedge = useCallback(async (wedge) => {
    setSelectedWedge(wedge);
    setError(null);
    setStage('training');

    // Generate snapshot_id once + persist for refresh-recovery.
    let snapshotId = sessionStorage.getItem(SESSION_KEY);
    if (!snapshotId) {
      snapshotId = crypto.randomUUID();
      sessionStorage.setItem(SESSION_KEY, snapshotId);
    }

    try {
      // CLI-only wedges send a stub item (the web flow can't read the
      // user's local filesystem). The server-side rule extractor
      // treats `quickstart-stub` as recognised-but-not-persisted, so
      // training still completes — but with zero entities created.
      // The done-screen message handles this case explicitly.
      const items = wedge.requiresCli
        ? [{ kind: 'quickstart-stub', channel: wedge.id, note: 'web-side stub for CLI-only wedge' }]
        : [{ kind: 'quickstart-stub', channel: wedge.id, note: 'server-side bootstrapper pending (PR-Q4b)' }];

      const resp = await bulkIngestTraining({
        source: wedge.id,
        items,
        snapshotId,
      });
      setTraining({
        runId: resp.run.id,
        status: resp.run.status,
        items_total: resp.run.items_total,
        items_processed: resp.run.items_processed,
        error: null,
      });
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'training dispatch failed');
      setStage('welcome');
    }
  }, []);

  // (3) Polling. Refs to avoid stale-closure issues when the timeout
  // re-fires across re-renders.
  const pollRef = useRef(null);
  useEffect(() => {
    if (stage !== 'training' || !training?.runId) return undefined;
    let cancelled = false;
    const POLL_MS = 2000;
    const DEADLINE_MS = 10 * 60 * 1000;  // mirror the CLI's 10-min cap
    const start = Date.now();

    const tick = async () => {
      if (cancelled) return;
      try {
        const run = await getTrainingRun(training.runId);
        if (cancelled) return;
        setTraining({
          runId: run.id,
          status: run.status,
          items_total: run.items_total,
          items_processed: run.items_processed,
          error: run.error,
        });
        if (run.status === 'complete') {
          // Stamp onboarding complete + clear resume state.
          sessionStorage.removeItem(SESSION_KEY);
          try {
            await completeOnboarding('web');
          } catch (e) {
            // Same fail-soft semantic as the CLI: training already
            // succeeded; the complete stamp can be retried.
            // eslint-disable-next-line no-console
            console.warn('completeOnboarding failed:', e);
          }
          setStage('done');
          return;
        }
        if (run.status === 'failed') {
          setError(run.error || 'training failed');
          setStage('welcome');
          return;
        }
        if (Date.now() - start >= DEADLINE_MS) {
          setError('training did not complete within 10 minutes — re-run from the dashboard later');
          setStage('welcome');
          return;
        }
        pollRef.current = setTimeout(tick, POLL_MS);
      } catch (e) {
        if (cancelled) return;
        setError(e?.response?.data?.detail || e.message || 'polling failed');
        setStage('welcome');
      }
    };

    pollRef.current = setTimeout(tick, POLL_MS);
    return () => {
      cancelled = true;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [stage, training?.runId]);

  return (
    <Container className="py-5" style={{ maxWidth: 720 }}>
      <Card>
        <Card.Body>
          {stage === 'loading' && <LoadingStage />}
          {stage === 'welcome' && (
            <WelcomeStage
              error={error}
              onStart={() => setStage('channel')}
              onSkip={handleSkip}
            />
          )}
          {stage === 'channel' && (
            <ChannelStage onPick={handlePickWedge} onBack={() => setStage('welcome')} />
          )}
          {stage === 'training' && (
            <TrainingStage wedge={selectedWedge} training={training} />
          )}
          {stage === 'done' && (
            <DoneStage wedge={selectedWedge} training={training} navigate={navigate} />
          )}
        </Card.Body>
      </Card>
    </Container>
  );
};

const LoadingStage = () => (
  <div className="text-center py-4">
    <Spinner animation="border" size="sm" />{' '}
    <span className="text-muted">Checking onboarding status…</span>
  </div>
);

const WelcomeStage = ({ error, onStart, onSkip }) => (
  <div>
    <h2 className="mb-3">Welcome to AgentProvision</h2>
    <p className="text-muted">
      Let's set up your first agent's memory. We'll learn from one of your
      existing tools — your inbox, calendar, Slack, or developer history —
      so the agent has real context to work from on its first chat.
    </p>
    <p className="text-muted small mb-4">
      Takes ~2 minutes. You can skip this and configure later from
      Settings → Onboarding.
    </p>
    {error && (
      <Alert variant="danger" className="small">
        {error}
      </Alert>
    )}
    <div className="d-flex justify-content-end gap-2">
      <Button variant="outline-secondary" onClick={onSkip}>
        Skip for now
      </Button>
      <Button variant="primary" onClick={onStart}>
        Get started →
      </Button>
    </div>
  </div>
);

const ChannelStage = ({ onPick, onBack }) => (
  <div>
    <h3 className="mb-3">Where should we learn from?</h3>
    <p className="text-muted small mb-4">
      Pick one source. We'll only read metadata (people, projects, recent
      activity) — never raw conversation bodies. You can connect more
      sources later.
    </p>
    <div className="d-grid gap-2 mb-3">
      {WEDGES.map((w) => (
        <Button
          key={w.id}
          variant="outline-primary"
          className="text-start"
          disabled={w.requiresCli}
          onClick={() => onPick(w)}
        >
          <div className="d-flex justify-content-between align-items-start">
            <div>
              <div className="fw-bold">{w.label}</div>
              <div className="small text-muted">{w.sublabel}</div>
            </div>
            {w.requiresCli && (
              <Badge bg="secondary" pill className="ms-2">
                CLI only
              </Badge>
            )}
          </div>
        </Button>
      ))}
    </div>
    <p className="small text-muted">
      The two CLI-only wedges need a terminal. Run{' '}
      <code>alpha quickstart --channel local_ai_cli</code> or{' '}
      <code>alpha quickstart --channel github_cli</code> if you'd rather seed
      from local tooling.
    </p>
    <div className="d-flex justify-content-start">
      <Button variant="link" onClick={onBack}>
        ← Back
      </Button>
    </div>
  </div>
);

const TrainingStage = ({ wedge, training }) => {
  const total = training?.items_total ?? 0;
  const processed = training?.items_processed ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  return (
    <div>
      <h3 className="mb-3">Training memory…</h3>
      <p className="text-muted">
        Source: <strong>{wedge?.label || training?.source || '—'}</strong>
      </p>
      <ProgressBar
        animated
        now={pct}
        label={`${processed} / ${total}`}
        className="mb-3"
      />
      <p className="small text-muted">
        Status: <code>{training?.status || 'pending'}</code>
      </p>
      <p className="small text-muted">
        This takes ~2 minutes for most accounts. You can leave this tab
        open — your agent will be ready by the time training finishes.
      </p>
    </div>
  );
};

const DoneStage = ({ wedge, training, navigate }) => {
  // If the wedge was CLI-only OR a stub-source, no entities actually
  // landed. Be honest about that — promising "your agent knows you
  // now" when the graph is empty is the cascade-memo anti-pattern in
  // a UI wrapper.
  const stubOnly = wedge?.requiresCli || (training?.items_processed ?? 0) === 0;
  return (
    <div>
      <h2 className="mb-3">{stubOnly ? 'Onboarding noted ✓' : 'Memory ready ✓'}</h2>
      {stubOnly ? (
        <p className="text-muted">
          We marked your tenant as onboarded so you won't see this wizard
          again. To actually seed your agent's memory, either run{' '}
          <code>alpha quickstart</code> from your terminal or connect one of
          the OAuth sources (Gmail / Slack) once their server-side
          bootstrappers ship — tracked as PR-Q4b.
        </p>
      ) : (
        <p className="text-muted">
          We've absorbed <strong>{training?.items_processed ?? 0}</strong>{' '}
          items from your <strong>{wedge?.label}</strong>. Your agent has
          real context now.
        </p>
      )}
      <p className="text-muted small mb-4">
        Try asking it: <em>"what should I work on next?"</em>
      </p>
      <div className="d-flex justify-content-end gap-2">
        <Button variant="outline-secondary" onClick={() => navigate('/dashboard')}>
          Dashboard
        </Button>
        <Button variant="primary" onClick={() => navigate('/chat')}>
          Open chat →
        </Button>
      </div>
    </div>
  );
};

export default OnboardingPage;
