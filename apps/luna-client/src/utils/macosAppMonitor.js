export const MACOS_APP_MONITOR_EVENT_SCHEMA = 'agentprovision.macos_app_monitor_event.v1';

function safeString(value, maxLength = 120) {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.length > maxLength ? trimmed.slice(0, maxLength) : trimmed;
}

function safeInteger(value, fallback = null) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) return fallback;
  return Math.floor(parsed);
}

function safeBoolean(value) {
  return value === true;
}

function safeUuid(value) {
  const uuid = safeString(value, 96);
  if (!uuid) return null;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(uuid)
    ? uuid.toLowerCase()
    : null;
}

function safeContextId(value, toApp) {
  const contextId = safeString(value, 120);
  if (!contextId) return null;
  const separator = contextId.lastIndexOf(':');
  if (separator <= 0 || separator === contextId.length - 1) return null;

  const appLabel = compactAppLabel(contextId.slice(0, separator), 80);
  const hash = contextId.slice(separator + 1);
  if (appLabel !== toApp || !/^[0-9a-f]+$/i.test(hash)) return null;
  return `${appLabel}:${hash.toLowerCase()}`;
}

export function compactAppLabel(value, maxLength = 28) {
  const label = safeString(value, maxLength + 1);
  if (!label) return null;
  return label.length > maxLength ? `${label.slice(0, maxLength - 1).trimEnd()}...` : label;
}

export function activeAppLabelFromMonitorEvent(payload) {
  return compactAppLabel(payload?.to_app);
}

export function sanitizeMacosAppMonitorEvent(payload, shellId) {
  if (
    !payload
    || typeof payload !== 'object'
    || payload.schema !== MACOS_APP_MONITOR_EVENT_SCHEMA
    || payload.type !== 'app_switch'
  ) {
    return null;
  }

  const toApp = compactAppLabel(payload.to_app, 80);
  if (!toApp) return null;

  const eventId = safeUuid(payload.event_id);
  if (!eventId) return null;

  const sanitized = {
    schema: MACOS_APP_MONITOR_EVENT_SCHEMA,
    event_id: eventId,
    type: 'app_switch',
    platform: 'macos',
    monitor_source: 'tauri_activity_tracker',
    detail_level: 'metadata_only',
    from_app: compactAppLabel(payload.from_app, 80) || '',
    to_app: toApp,
    duration_secs: safeInteger(payload.duration_secs, 0),
    timestamp: safeInteger(payload.timestamp),
    observed_at_ms: safeInteger(payload.observed_at_ms),
    active_context_id: safeContextId(payload.active_context_id, toApp),
    window_title_present: safeBoolean(payload.window_title_present),
    window_title_chars: safeInteger(payload.window_title_chars, 0),
  };

  const sourceShell = safeString(shellId, 96);
  if (sourceShell) sanitized.source_shell = sourceShell;

  Object.keys(sanitized).forEach((key) => {
    if (sanitized[key] === null || sanitized[key] === undefined) {
      delete sanitized[key];
    }
  });

  return sanitized;
}
