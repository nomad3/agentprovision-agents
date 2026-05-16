/*
 * InlineCliPicker — compact CLI-platform switcher for the chat thread
 * header.
 *
 * Surfaces the same `tenant_features.default_cli_platform` knob that the
 * Integrations page exposes via DefaultCliSelector, but as a small
 * inline select so users don't have to leave the active chat session
 * just to swap routers. Keeps the chat in flow.
 *
 * No "connected CLIs" filtering here — the chat surface doesn't have
 * the integration polling context, and the backend resolver already
 * falls over to the next available CLI on quota/auth failures. Users
 * who pick a CLI they haven't connected will see Auto behaviour kick in
 * on the next turn; no harm.
 */
import { useEffect, useState } from 'react';
import { brandingService } from '../services/branding';
import './InlineCliPicker.css';

const AUTO_VALUE = '__auto__';
const CLI_OPTIONS = [
  { value: 'claude_code', label: 'Claude Code' },
  { value: 'codex', label: 'Codex' },
  { value: 'gemini_cli', label: 'Gemini CLI' },
  { value: 'copilot_cli', label: 'Copilot CLI' },
];

const InlineCliPicker = () => {
  const [current, setCurrent] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const features = await brandingService.getFeatures();
        if (!cancelled) {
          setCurrent(features?.default_cli_platform || null);
          setLoaded(true);
        }
      } catch (_err) {
        if (!cancelled) {
          setLoaded(true);
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleChange = async (e) => {
    const value = e.target.value;
    const next = value === AUTO_VALUE ? null : value;
    setSaving(true);
    setError(null);
    try {
      await brandingService.updateFeatures({ default_cli_platform: next });
      setCurrent(next);
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
    <div className="inline-cli-picker" title="Switch which CLI handles this chat. Falls back to Auto if the picked CLI isn't connected.">
      <label htmlFor="inline-cli-picker-select" className="inline-cli-picker-label">CLI</label>
      <select
        id="inline-cli-picker-select"
        className="inline-cli-picker-select"
        value={selectValue}
        onChange={handleChange}
        disabled={saving}
        aria-label="Default CLI platform"
      >
        <option value={AUTO_VALUE}>Auto</option>
        {CLI_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      {saving && <span className="inline-cli-picker-saving">…</span>}
      {error && <span className="inline-cli-picker-error" title={error}>!</span>}
    </div>
  );
};

export default InlineCliPicker;
