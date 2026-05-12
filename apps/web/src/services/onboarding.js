/**
 * Onboarding + training-ingestion API client.
 *
 * Wraps the four endpoints `ap quickstart` calls on the CLI side so
 * the React SPA can drive the same flow. See:
 *   - apps/api/app/api/v1/onboarding.py     (status / defer / complete)
 *   - apps/api/app/api/v1/memory_training.py (bulk-ingest + run polling)
 *
 * No state lives in this module — it's a thin function-per-endpoint
 * surface. The OnboardingFlow component owns the multi-step state.
 */
import api from './api';

/** GET /api/v1/onboarding/status — drives the route-guard auto-redirect. */
export async function getOnboardingStatus() {
  const resp = await api.get('/onboarding/status');
  return resp.data;
}

/**
 * POST /api/v1/onboarding/defer — user pressed Skip. Suppresses the
 * route guard's redirect on subsequent dashboard mounts but doesn't
 * block an explicit visit to /onboarding/welcome.
 */
export async function deferOnboarding() {
  await api.post('/onboarding/defer', {});
}

/**
 * POST /api/v1/onboarding/complete — stamps onboarded_at. The server
 * stores the source so we always pass `web` from this surface; the
 * CLI passes `cli`.
 */
export async function completeOnboarding(source = 'web') {
  await api.post('/onboarding/complete', { source });
}

/**
 * POST /api/v1/memory/training/bulk-ingest — idempotent on
 * (tenant_id, snapshot_id). The web flow generates snapshot_id once
 * at wedge-pick time and persists it in sessionStorage so a refresh
 * mid-training picks up the same run row instead of spawning a
 * parallel workflow.
 */
export async function bulkIngestTraining({ source, items, snapshotId }) {
  const resp = await api.post('/memory/training/bulk-ingest', {
    source,
    items,
    snapshot_id: snapshotId,
  });
  return resp.data;
}

/** GET /api/v1/memory/training/{run_id} — status poll until terminal. */
export async function getTrainingRun(runId) {
  const resp = await api.get(`/memory/training/${runId}`);
  return resp.data;
}

/**
 * Six wedge channels — wire format must match
 * `app/schemas/training_run.py::Source`. The web picker uses these
 * IDs as React keys + payload values. Labels here mirror the CLI
 * picker labels in `apps/agentprovision-cli/src/commands/quickstart.rs`
 * `WedgeChannel::label()` for surface consistency.
 */
export const WEDGES = [
  {
    id: 'local_ai_cli',
    label: 'Local AI CLI history',
    sublabel: 'Claude / Codex / Gemini / Copilot session metadata',
    // local_ai_cli wedge is CLI-only — the web flow can't read the
    // user's local filesystem. Disabled in the picker; the
    // explainer points at `ap quickstart` instead.
    requiresCli: true,
  },
  {
    id: 'github_cli',
    label: 'GitHub CLI',
    sublabel: 'Your repos / orgs / PRs via gh',
    requiresCli: true,
  },
  {
    id: 'gmail',
    label: 'Gmail',
    sublabel: 'Recent inbox — people, projects, commitments',
    requiresCli: false,
  },
  {
    id: 'calendar',
    label: 'Google Calendar',
    sublabel: 'Upcoming events — meetings, attendees',
    requiresCli: false,
  },
  {
    id: 'slack',
    label: 'Slack',
    sublabel: 'Workspace + recent channels',
    requiresCli: false,
  },
  {
    id: 'whatsapp',
    label: 'WhatsApp',
    sublabel: 'Contacts + recent chats',
    requiresCli: false,
  },
];
