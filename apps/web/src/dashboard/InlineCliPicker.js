/*
 * InlineCliPicker — compact CLI-platform switcher for the chat thread
 * header.
 *
 * Surfaces the same `tenant_features.default_cli_platform` knob that the
 * Integrations page exposes via DefaultCliSelector, but as a small
 * inline select so users don't have to leave the active chat session
 * just to swap routers. Keeps the chat in flow.
 *
 * Scope is tenant-wide, not per-chat: the underlying knob is
 * `tenant_features.default_cli_platform`. The label + tooltip make
 * that explicit so a user toggling it from inside one chat doesn't
 * think they're only affecting the current thread.
 *
 * No "connected CLIs" filtering here — the chat surface doesn't have
 * the integration polling context, and the backend resolver already
 * falls over to the next available CLI on quota/auth failures. Users
 * who pick a CLI they haven't connected will see Auto behaviour kick in
 * on the next turn; no harm.
 */
import { useEffect, useId, useState } from 'react';
import { brandingService } from '../services/branding';
import './InlineCliPicker.css';

const AUTO_VALUE = '__auto__';
const CLI_OPTIONS = [
  { value: 'claude_code', label: 'Claude Code' },
  { value: 'codex', label: 'Codex' },
  { value: 'gemini_cli', label: 'Gemini CLI' },
  { value: 'copilot_cli', label: 'Copilot CLI' },
];

// How long the "saved ✓" affordance stays on screen after a successful
// write. Matches the pattern used by DefaultCliSelector — short enough
// not to clutter the header but long enough for the user to notice.
const SAVED_FLASH_MS = 2000;

const InlineCliPicker = () => {
  const [current, setCurrent] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);
  const [error, setError] = useState(null);

  // useId() gives a stable, unique id per mounted instance. Required
  // because the dashboard renders one InlineCliPicker per <ChatTab>,
  // and split-pane layouts mount multiple ChatTabs side-by-side. A
  // hardcoded id duplicated across instances breaks <label for=...>
  // click-to-focus on every instance after the first.
  const selectId = useId();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const features = await brandingService.getFeatures();
        if (!cancelled) {
          setCurrent(features?.default_cli_platform || null);
          setLoaded(true);
        }
      } catch (err) {
        // Surface the failure instead of swallowing it. Mirrors the
        // DefaultCliSelector pattern so the user has a recoverable
        // hint that something's off rather than a silently-stuck Auto.
        // eslint-disable-next-line no-console
        console.warn('InlineCliPicker: failed to load features', err);
        if (!cancelled) {
          setError('Could not load tenant default CLI');
          setLoaded(true);
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Auto-expire the "Saved" flash so it doesn't linger past its welcome.
  useEffect(() => {
    if (!savedAt) return undefined;
    const t = setTimeout(() => setSavedAt(null), SAVED_FLASH_MS);
    return () => clearTimeout(t);
  }, [savedAt]);

  const handleChange = async (e) => {
    const value = e.target.value;
    const next = value === AUTO_VALUE ? null : value;
    setSaving(true);
    setError(null);
    try {
      await brandingService.updateFeatures({ default_cli_platform: next });
      setCurrent(next);
      setSavedAt(Date.now());
    } catch (_err) {
      setError('Save failed');
    } finally {
      setSaving(false);
    }
  };

  // Hide until we know the current default — avoids the select
  // flickering from Auto to the actual value on mount.
  if (!loaded) return null;

  const selectValue = current || AUTO_VALUE;

  return (
    <div
      className="inline-cli-picker"
      title="Tenant default CLI — applies to every chat. Falls back to Auto if the picked CLI isn't connected."
    >
      <label htmlFor={selectId} className="inline-cli-picker-label">Tenant CLI</label>
      <select
        id={selectId}
        className="inline-cli-picker-select"
        value={selectValue}
        onChange={handleChange}
        disabled={saving}
        aria-label="Tenant default CLI platform"
      >
        <option value={AUTO_VALUE}>Auto</option>
        {CLI_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      {saving && <span className="inline-cli-picker-saving">…</span>}
      {!saving && savedAt && (
        <span className="inline-cli-picker-saved" aria-label="Saved">✓</span>
      )}
      {error && (
        <span className="inline-cli-picker-error" title={error}>
          {error}
        </span>
      )}
    </div>
  );
};

export default InlineCliPicker;
