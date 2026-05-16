import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import InlineCliPicker from '../InlineCliPicker';

jest.mock('../../services/branding', () => ({
  brandingService: {
    getFeatures: jest.fn(),
    updateFeatures: jest.fn(),
  },
}));

const { brandingService } = require('../../services/branding');

describe('InlineCliPicker', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    brandingService.getFeatures.mockResolvedValue({ default_cli_platform: null });
    brandingService.updateFeatures.mockResolvedValue({});
  });

  test('renders nothing while getFeatures is pending', async () => {
    // Hold the promise un-resolved so the loaded state never flips.
    let resolveFeatures;
    brandingService.getFeatures.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveFeatures = resolve;
      }),
    );
    render(<InlineCliPicker />);
    // Picker hides itself entirely until loaded — no select, no label.
    expect(screen.queryByLabelText(/Tenant default CLI platform/i)).not.toBeInTheDocument();
    // Resolve so test teardown doesn't leak a pending act.
    await act(async () => {
      resolveFeatures({ default_cli_platform: null });
    });
  });

  test('renders select after getFeatures resolves with Auto as the default', async () => {
    render(<InlineCliPicker />);
    const select = await screen.findByLabelText(/Tenant default CLI platform/i);
    expect(select).toBeInTheDocument();
    expect(select.value).toBe('__auto__');
    // Label reflects the tenant-wide scope.
    expect(screen.getByText('Tenant CLI')).toBeInTheDocument();
  });

  test('reflects the stored default from getFeatures', async () => {
    brandingService.getFeatures.mockResolvedValue({ default_cli_platform: 'codex' });
    render(<InlineCliPicker />);
    const select = await screen.findByLabelText(/Tenant default CLI platform/i);
    expect(select.value).toBe('codex');
  });

  test('change handler saves selection via updateFeatures', async () => {
    render(<InlineCliPicker />);
    const select = await screen.findByLabelText(/Tenant default CLI platform/i);
    fireEvent.change(select, { target: { value: 'codex' } });
    await waitFor(() =>
      expect(brandingService.updateFeatures).toHaveBeenCalledWith({
        default_cli_platform: 'codex',
      }),
    );
  });

  test('"Auto" sends null to clear tenant default', async () => {
    brandingService.getFeatures.mockResolvedValue({ default_cli_platform: 'codex' });
    render(<InlineCliPicker />);
    const select = await screen.findByLabelText(/Tenant default CLI platform/i);
    fireEvent.change(select, { target: { value: '__auto__' } });
    await waitFor(() =>
      expect(brandingService.updateFeatures).toHaveBeenCalledWith({
        default_cli_platform: null,
      }),
    );
  });

  test('shows saved affordance after successful save', async () => {
    render(<InlineCliPicker />);
    const select = await screen.findByLabelText(/Tenant default CLI platform/i);
    fireEvent.change(select, { target: { value: 'claude_code' } });
    // ✓ appears after the save resolves.
    expect(await screen.findByLabelText('Saved')).toBeInTheDocument();
  });

  test('unmount during pending getFeatures does not call setState (no warning)', async () => {
    let resolveFeatures;
    brandingService.getFeatures.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveFeatures = resolve;
      }),
    );
    // Capture console.error so we'd see any "called setState on unmounted" warning.
    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    const { unmount } = render(<InlineCliPicker />);
    unmount();
    await act(async () => {
      resolveFeatures({ default_cli_platform: 'codex' });
    });
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });

  test('surfaces error indicator when getFeatures rejects', async () => {
    const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
    brandingService.getFeatures.mockRejectedValue(new Error('boom'));
    render(<InlineCliPicker />);
    // After load completes the picker should still mount (loaded=true)
    // and surface a visible error indicator.
    expect(
      await screen.findByText(/Could not load tenant default CLI/i),
    ).toBeInTheDocument();
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  test('each instance gets a unique id (split-pane safe)', async () => {
    render(<InlineCliPicker />);
    render(<InlineCliPicker />);
    // Both pickers should mount and expose their selects via the aria-label.
    const selects = await screen.findAllByLabelText(/Tenant default CLI platform/i);
    expect(selects).toHaveLength(2);
    const id1 = selects[0].getAttribute('id');
    const id2 = selects[1].getAttribute('id');
    expect(id1).toBeTruthy();
    expect(id2).toBeTruthy();
    expect(id1).not.toEqual(id2);
  });
});
