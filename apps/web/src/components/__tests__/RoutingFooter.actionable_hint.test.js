/**
 * Phase 3 commit 6 — actionable_hint resolution tests.
 *
 * Verifies the platform-specific → generic → English-literal fallback
 * chain for actionable_hint i18n keys emitted by the resilient
 * orchestrator (e.g. ``cli.errors.needs_auth.claude_code``).
 */
import { render, screen } from '@testing-library/react';
import RoutingFooter, { resolveActionableHint } from '../RoutingFooter';

// Mock react-i18next so we control the translation lookup table.
jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, opts) => {
    const dict = global.__I18N_DICT || {};
    if (Object.prototype.hasOwnProperty.call(dict, key)) {
      return dict[key];
    }
    if (opts && Object.prototype.hasOwnProperty.call(opts, 'defaultValue')) {
      return opts.defaultValue;
    }
    return key;
  } }),
}));

beforeEach(() => {
  global.__I18N_DICT = {};
});

afterEach(() => {
  delete global.__I18N_DICT;
});


// ── resolveActionableHint helper ────────────────────────────────────────

describe('resolveActionableHint', () => {
  test('renders specific platform key when present', () => {
    const t = (key, opts) => {
      if (key === 'cli.errors.needs_auth.claude_code') {
        return 'Reconnect Claude Code';
      }
      return opts?.defaultValue ?? key;
    };
    expect(resolveActionableHint(t, 'cli.errors.needs_auth.claude_code'))
      .toBe('Reconnect Claude Code');
  });

  test('falls back to generic when only generic is present', () => {
    const t = (key, opts) => {
      if (key === 'cli.errors.needs_auth') {
        return 'Reconnect this CLI';
      }
      return opts?.defaultValue ?? key;
    };
    expect(resolveActionableHint(t, 'cli.errors.needs_auth.gemini_cli'))
      .toBe('Reconnect this CLI');
  });

  test('falls back to English literal when neither key is registered', () => {
    const t = (key, opts) => opts?.defaultValue ?? key;
    const out = resolveActionableHint(t, 'cli.errors.needs_auth.copilot_cli');
    // Hard-coded English literal for needs_auth
    expect(out).toMatch(/Reconnect/i);
  });

  test('returns null when hintKey is null', () => {
    const t = () => 'should not be called';
    expect(resolveActionableHint(t, null)).toBeNull();
  });

  test('handles workspace_untrusted with no platform suffix', () => {
    const t = (key, opts) => {
      if (key === 'cli.errors.workspace_untrusted') {
        return 'Workspace not trusted';
      }
      return opts?.defaultValue ?? key;
    };
    expect(resolveActionableHint(t, 'cli.errors.workspace_untrusted'))
      .toBe('Workspace not trusted');
  });
});


// ── RoutingFooter rendering integration ─────────────────────────────────

describe('RoutingFooter actionable_hint surfacing', () => {
  test('renders actionable hint message when hint key is present in summary', () => {
    global.__I18N_DICT = {
      'cli.errors.needs_auth.claude_code': 'Reconnect Claude Code in Settings.',
    };
    const ctx = {
      tokens_used: 100,
      routing_summary: {
        served_by: 'Codex',
        served_by_platform: 'codex',
        chain_length: 2,
        actionable_hint: 'cli.errors.needs_auth.claude_code',
      },
    };
    render(<RoutingFooter context={ctx} />);
    expect(screen.getByTestId('routing-actionable-hint'))
      .toHaveTextContent('Reconnect Claude Code in Settings.');
  });

  test('omits actionable hint node when no hint key set', () => {
    const ctx = {
      tokens_used: 100,
      routing_summary: {
        served_by: 'Claude Code',
        served_by_platform: 'claude_code',
        chain_length: 1,
      },
    };
    render(<RoutingFooter context={ctx} />);
    expect(screen.queryByTestId('routing-actionable-hint')).toBeNull();
  });

  test('falls back to generic key when platform key missing', () => {
    global.__I18N_DICT = {
      'cli.errors.needs_auth': 'Reconnect this CLI.',
    };
    const ctx = {
      tokens_used: 100,
      routing_summary: {
        served_by: 'Codex',
        served_by_platform: 'codex',
        chain_length: 2,
        actionable_hint: 'cli.errors.needs_auth.gemini_cli',
      },
    };
    render(<RoutingFooter context={ctx} />);
    expect(screen.getByTestId('routing-actionable-hint'))
      .toHaveTextContent('Reconnect this CLI.');
  });
});
