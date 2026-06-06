import { describe, expect, it } from 'vitest';
import {
  MACOS_APP_MONITOR_EVENT_SCHEMA,
  activeAppLabelFromMonitorEvent,
  sanitizeMacosAppMonitorEvent,
} from '../macosAppMonitor';

describe('macosAppMonitor', () => {
  it('sanitizes native app-monitor events before API/UI forwarding', () => {
    const sanitized = sanitizeMacosAppMonitorEvent({
      schema: MACOS_APP_MONITOR_EVENT_SCHEMA,
      event_id: '11111111-1111-4111-8111-111111111111',
      type: 'app_switch',
      from_app: 'Code',
      to_app: 'Terminal',
      duration_secs: 12.9,
      timestamp: 12345,
      observed_at_ms: 12345000,
      active_context_id: 'Terminal:abc123',
      window_title_present: true,
      window_title_chars: 24,
      window_title: 'secret repo window title',
      subprocess: { active_processes: [{ args: 'secret args' }] },
      clipboard: 'secret clipboard',
    }, 'desktop-test-shell');

    expect(sanitized).toEqual(expect.objectContaining({
      schema: MACOS_APP_MONITOR_EVENT_SCHEMA,
      event_id: '11111111-1111-4111-8111-111111111111',
      type: 'app_switch',
      platform: 'macos',
      monitor_source: 'tauri_activity_tracker',
      detail_level: 'metadata_only',
      from_app: 'Code',
      to_app: 'Terminal',
      duration_secs: 12,
      timestamp: 12345,
      observed_at_ms: 12345000,
      active_context_id: 'Terminal:abc123',
      window_title_present: true,
      window_title_chars: 24,
      source_shell: 'desktop-test-shell',
    }));
    expect(JSON.stringify(sanitized)).not.toContain('secret repo window title');
    expect(JSON.stringify(sanitized)).not.toContain('secret args');
    expect(JSON.stringify(sanitized)).not.toContain('secret clipboard');
  });

  it('rejects malformed monitor events', () => {
    expect(sanitizeMacosAppMonitorEvent(null, 'desktop-test-shell')).toBeNull();
    expect(sanitizeMacosAppMonitorEvent({ type: 'clipboard' }, 'desktop-test-shell')).toBeNull();
    expect(sanitizeMacosAppMonitorEvent({ type: 'app_switch' }, 'desktop-test-shell')).toBeNull();
    expect(sanitizeMacosAppMonitorEvent({
      schema: 'agentprovision.macos_app_monitor_event.v0',
      type: 'app_switch',
      to_app: 'Terminal',
    }, 'desktop-test-shell')).toBeNull();
    expect(sanitizeMacosAppMonitorEvent({
      schema: MACOS_APP_MONITOR_EVENT_SCHEMA,
      event_id: '11111111-1111-4111-8111-111111111111',
      type: 'app_switch',
      to_app: 'Terminal',
      active_context_id: 'Terminal:secret repo title',
    }, 'desktop-test-shell')).not.toHaveProperty('active_context_id');
    expect(sanitizeMacosAppMonitorEvent({
      schema: MACOS_APP_MONITOR_EVENT_SCHEMA,
      type: 'app_switch',
      to_app: 'Terminal',
      event_id: 'secret repo title',
    }, 'desktop-test-shell')).toBeNull();
  });

  it('extracts compact app labels without raw window context', () => {
    expect(activeAppLabelFromMonitorEvent({ to_app: 'Terminal' })).toBe('Terminal');
    expect(activeAppLabelFromMonitorEvent({ app_name: 'Terminal' })).toBeNull();
    expect(activeAppLabelFromMonitorEvent({
      to_app: 'Very Long Application Name That Needs Truncation',
      window_title: 'secret title',
    })).toBe('Very Long Application Name...');
  });
});
