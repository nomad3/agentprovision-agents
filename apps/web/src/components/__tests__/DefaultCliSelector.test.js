import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import DefaultCliSelector from '../DefaultCliSelector';

jest.mock('../../services/branding', () => ({
  brandingService: {
    getFeatures: jest.fn(),
    updateFeatures: jest.fn(),
  },
}));

const { brandingService } = require('../../services/branding');


describe('DefaultCliSelector', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    brandingService.getFeatures.mockResolvedValue({ default_cli_platform: null });
    brandingService.updateFeatures.mockResolvedValue({});
  });

  test('hidden when zero CLIs are connected — autodetect handles single-tenant case', async () => {
    const { container } = render(
      <DefaultCliSelector configs={[]} credentialStatuses={{}} />,
    );
    await waitFor(() => expect(brandingService.getFeatures).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  test('hidden when only one CLI is connected — no choice to make', async () => {
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'me@example.com' },
    ];
    const { container } = render(
      <DefaultCliSelector configs={configs} credentialStatuses={{}} />,
    );
    await waitFor(() => expect(brandingService.getFeatures).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  test('renders selector when ≥2 CLIs are connected', async () => {
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'gemini_cli', enabled: true, account_email: 'a@b.com' },
    ];
    render(<DefaultCliSelector configs={configs} credentialStatuses={{}} />);
    await waitFor(() => expect(screen.getByText(/Default CLI/)).toBeInTheDocument());
    const select = screen.getByLabelText(/Default CLI platform/i);
    expect(select).toBeInTheDocument();
    // Auto + the two connected CLIs only — Codex and Claude Code aren't shown.
    const optionTexts = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(optionTexts).toEqual(expect.arrayContaining([
      'Auto (recommended)',
      'GitHub Copilot CLI',
      'Gemini CLI',
    ]));
    expect(optionTexts).not.toContain('Claude Code');
    expect(optionTexts).not.toContain('Codex');
  });

  test('renders when gemini_cli is connected via gmail (auth piggy-back)', async () => {
    // The backend resolver treats gmail/google_drive/google_calendar as
    // proof-of-credential for gemini_cli. UI must mirror that or the
    // selector won't appear for tenants who only connected Gmail.
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'gmail', enabled: true, account_email: 'a@b.com' },
    ];
    render(<DefaultCliSelector configs={configs} credentialStatuses={{}} />);
    await waitFor(() => expect(screen.getByText(/Default CLI/)).toBeInTheDocument());
    const select = screen.getByLabelText(/Default CLI platform/i);
    const optionTexts = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(optionTexts).toEqual(expect.arrayContaining(['Gemini CLI', 'GitHub Copilot CLI']));
  });

  test('shows current default loaded from getFeatures', async () => {
    brandingService.getFeatures.mockResolvedValue({ default_cli_platform: 'copilot_cli' });
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'gemini_cli', enabled: true, account_email: 'a@b.com' },
    ];
    render(<DefaultCliSelector configs={configs} credentialStatuses={{}} />);
    await waitFor(() => expect(screen.getByLabelText(/Default CLI platform/i).value).toBe('copilot_cli'));
  });

  test('saves new default via updateFeatures on change', async () => {
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'gemini_cli', enabled: true, account_email: 'a@b.com' },
    ];
    render(<DefaultCliSelector configs={configs} credentialStatuses={{}} />);
    const select = await screen.findByLabelText(/Default CLI platform/i);
    fireEvent.change(select, { target: { value: 'copilot_cli' } });
    await waitFor(() =>
      expect(brandingService.updateFeatures).toHaveBeenCalledWith({
        default_cli_platform: 'copilot_cli',
      }),
    );
  });

  test('"Auto" sends null to clear tenant default — backend autodetects per turn', async () => {
    brandingService.getFeatures.mockResolvedValue({ default_cli_platform: 'copilot_cli' });
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'gemini_cli', enabled: true, account_email: 'a@b.com' },
    ];
    render(<DefaultCliSelector configs={configs} credentialStatuses={{}} />);
    const select = await screen.findByLabelText(/Default CLI platform/i);
    fireEvent.change(select, { target: { value: '__auto__' } });
    await waitFor(() =>
      expect(brandingService.updateFeatures).toHaveBeenCalledWith({
        default_cli_platform: null,
      }),
    );
  });

  test('shows recoverable error when save fails', async () => {
    brandingService.updateFeatures.mockRejectedValue(new Error('500'));
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'gemini_cli', enabled: true, account_email: 'a@b.com' },
    ];
    render(<DefaultCliSelector configs={configs} credentialStatuses={{}} />);
    const select = await screen.findByLabelText(/Default CLI platform/i);
    fireEvent.change(select, { target: { value: 'copilot_cli' } });
    await waitFor(() => expect(screen.getByText(/Could not save/)).toBeInTheDocument());
  });

  test('falls back to Auto when stored default is no longer available', async () => {
    // Tenant default was previously copilot_cli; admin then disconnected
    // GitHub. The selector must show "Auto" rather than a stale option
    // pointing to a CLI that's no longer connected.
    brandingService.getFeatures.mockResolvedValue({ default_cli_platform: 'copilot_cli' });
    const configs = [
      { integration_name: 'gemini_cli', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'claude_code', enabled: true, account_email: 'a@b.com' },
    ];
    render(<DefaultCliSelector configs={configs} credentialStatuses={{}} />);
    const select = await screen.findByLabelText(/Default CLI platform/i);
    expect(select.value).toBe('__auto__');
  });

  test('disabled enabled=false configs do not count as connected', async () => {
    const configs = [
      { integration_name: 'github', enabled: false, account_email: 'a@b.com' },
      { integration_name: 'gemini_cli', enabled: true, account_email: 'a@b.com' },
    ];
    const { container } = render(
      <DefaultCliSelector configs={configs} credentialStatuses={{}} />,
    );
    await waitFor(() => expect(brandingService.getFeatures).toHaveBeenCalled());
    // Only one CLI effectively connected → selector hidden.
    expect(container.firstChild).toBeNull();
  });

  // ── Subscription-OAuth CLI auth-state path (PR #477) ──────────────
  //
  // claude_code / codex / gemini_cli connected via the dedicated
  // /<cli>-auth flow store a session_token in the vault but don't set
  // `account_email` and aren't `auth_type='manual'` — neither of the
  // two config-derived signals fires. The selector must read the
  // per-CLI `/<cli>-auth/status` connected flag instead.

  test('claudeAuthState.connected surfaces Claude Code in the dropdown', async () => {
    // Only github config carries account_email; claude_code config has
    // neither account_email nor an entry in credentialStatuses. Without
    // the auth-state signal the dropdown would exclude Claude Code.
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'claude_code', enabled: true },
    ];
    render(
      <DefaultCliSelector
        configs={configs}
        credentialStatuses={{}}
        claudeAuthState={{ status: 'connected', connected: true }}
      />,
    );
    await waitFor(() => expect(screen.getByText(/Default CLI/)).toBeInTheDocument());
    const select = screen.getByLabelText(/Default CLI platform/i);
    const optionTexts = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(optionTexts).toEqual(expect.arrayContaining(['Claude Code', 'GitHub Copilot CLI']));
  });

  test('codexAuthState.connected surfaces Codex in the dropdown', async () => {
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'codex', enabled: true },
    ];
    render(
      <DefaultCliSelector
        configs={configs}
        credentialStatuses={{}}
        codexAuthState={{ status: 'connected', connected: true }}
      />,
    );
    await waitFor(() => expect(screen.getByText(/Default CLI/)).toBeInTheDocument());
    const select = screen.getByLabelText(/Default CLI platform/i);
    const optionTexts = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(optionTexts).toEqual(expect.arrayContaining(['Codex', 'GitHub Copilot CLI']));
  });

  test('geminiCliAuthState.connected surfaces Gemini CLI even without sibling Google integrations', async () => {
    // Distinct from the existing gmail-piggy-back test: this case has
    // NO Google integrations at all, only a direct gemini_cli OAuth.
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'gemini_cli', enabled: true },
    ];
    render(
      <DefaultCliSelector
        configs={configs}
        credentialStatuses={{}}
        geminiCliAuthState={{ status: 'connected', connected: true }}
      />,
    );
    await waitFor(() => expect(screen.getByText(/Default CLI/)).toBeInTheDocument());
    const select = screen.getByLabelText(/Default CLI platform/i);
    const optionTexts = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(optionTexts).toEqual(expect.arrayContaining(['Gemini CLI', 'GitHub Copilot CLI']));
  });

  test('stored default of claude_code preserved when claudeAuthState.connected=true', async () => {
    // Returning user scenario: tenant previously set Claude Code as
    // default, page reloads. claudeAuthState.connected=true must hold
    // the stored default in place (not fall back to Auto).
    brandingService.getFeatures.mockResolvedValue({ default_cli_platform: 'claude_code' });
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'claude_code', enabled: true },
    ];
    render(
      <DefaultCliSelector
        configs={configs}
        credentialStatuses={{}}
        claudeAuthState={{ status: 'connected', connected: true }}
      />,
    );
    const select = await screen.findByLabelText(/Default CLI platform/i);
    expect(select.value).toBe('claude_code');
  });

  test('connected=false in auth state does NOT add the CLI', async () => {
    // Defence: a stale `claudeAuthState` of `{ status: 'failed',
    // connected: false }` must not falsely surface Claude Code.
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'gemini_cli', enabled: true, account_email: 'a@b.com' },
    ];
    render(
      <DefaultCliSelector
        configs={configs}
        credentialStatuses={{}}
        claudeAuthState={{ status: 'failed', connected: false }}
        codexAuthState={{ status: 'idle', connected: false }}
      />,
    );
    await waitFor(() => expect(screen.getByText(/Default CLI/)).toBeInTheDocument());
    const select = screen.getByLabelText(/Default CLI platform/i);
    const optionTexts = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(optionTexts).not.toContain('Claude Code');
    expect(optionTexts).not.toContain('Codex');
  });

  test('missing auth-state props are treated as not-connected (back-compat)', async () => {
    // The new props are optional — existing callers that don't pass
    // them should see identical behaviour to pre-#477.
    const configs = [
      { integration_name: 'github', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'gemini_cli', enabled: true, account_email: 'a@b.com' },
      { integration_name: 'claude_code', enabled: true },  // no account_email
    ];
    render(<DefaultCliSelector configs={configs} credentialStatuses={{}} />);
    await waitFor(() => expect(screen.getByText(/Default CLI/)).toBeInTheDocument());
    const select = screen.getByLabelText(/Default CLI platform/i);
    const optionTexts = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(optionTexts).not.toContain('Claude Code');
  });
});
