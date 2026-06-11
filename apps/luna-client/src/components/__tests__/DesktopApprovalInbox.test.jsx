import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

const apiJsonMock = vi.fn();

vi.mock('../../api', () => ({
  apiJson: (...args) => apiJsonMock(...args),
}));

import DesktopApprovalInbox from '../DesktopApprovalInbox';

const pendingRequest = {
  request_id: '11111111-2222-4333-8444-555555555555',
  session_id: 'session-1',
  shell_id: 'desktop-shell-1',
  action: 'pointer_click',
  capability: 'pointer_control',
  status: 'pending',
  target_bundle_id: 'com.apple.TextEdit',
  reason: 'OCR text that must not render',
  created_at: '2026-06-11T22:40:00+00:00',
  expires_at: '2099-01-01T00:00:00+00:00',
  grant_present: false,
  grant_id: null,
  decided_at: null,
};

beforeEach(() => {
  apiJsonMock.mockReset();
});

describe('DesktopApprovalInbox', () => {
  it('does not load approvals before an active session exists', async () => {
    render(<DesktopApprovalInbox pollMs={0} />);

    expect(screen.getByRole('button', { name: /desktop approvals unavailable/i })).toBeDisabled();
    expect(apiJsonMock).not.toHaveBeenCalled();
  });

  it('loads pending desktop approval requests scoped to the active session', async () => {
    apiJsonMock.mockResolvedValue([pendingRequest]);

    render(<DesktopApprovalInbox sessionId="session-1" pollMs={0} />);

    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith(
        '/api/v1/desktop-control/grants/requests?session_id=session-1',
      );
    });

    fireEvent.click(screen.getByRole('button', { name: /desktop approvals/i }));
    expect(await screen.findByText('pointer_click')).toBeInTheDocument();
    expect(screen.getByText('com.apple.TextEdit')).toBeInTheDocument();
  });

  it('does not render the request reason in the approval panel', async () => {
    apiJsonMock.mockResolvedValue([pendingRequest]);

    render(<DesktopApprovalInbox sessionId="session-1" pollMs={0} />);
    fireEvent.click(screen.getByRole('button', { name: /desktop approvals/i }));

    expect(await screen.findByText('pointer_click')).toBeInTheDocument();
    expect(screen.queryByText(/OCR text that must not render/)).not.toBeInTheDocument();
  });

  it('approves with one bounded action and refreshes the list', async () => {
    let requests = [pendingRequest];
    apiJsonMock.mockImplementation((path, options) => {
      if (path.endsWith('/approve')) {
        requests = [];
        return Promise.resolve({ ...pendingRequest, status: 'approved', grant_id: 'grant-1' });
      }
      return Promise.resolve(requests);
    });

    render(<DesktopApprovalInbox sessionId="session-1" pollMs={0} />);
    fireEvent.click(screen.getByRole('button', { name: /desktop approvals/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));

    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith(
        '/api/v1/desktop-control/grants/requests/11111111-2222-4333-8444-555555555555/approve',
        {
          method: 'POST',
          body: JSON.stringify({ max_actions: 1, expires_in_seconds: 60 }),
        },
      );
    });
    expect(await screen.findByText('No pending approvals.')).toBeInTheDocument();
  });

  it('denies without sending a free-text reason and refreshes the list', async () => {
    let requests = [pendingRequest];
    apiJsonMock.mockImplementation((path, options) => {
      if (path.endsWith('/deny')) {
        requests = [];
        return Promise.resolve({ ...pendingRequest, status: 'denied' });
      }
      return Promise.resolve(requests);
    });

    render(<DesktopApprovalInbox sessionId="session-1" pollMs={0} />);
    fireEvent.click(screen.getByRole('button', { name: /desktop approvals/i }));
    fireEvent.click(await screen.findByRole('button', { name: 'Deny' }));

    await waitFor(() => {
      expect(apiJsonMock).toHaveBeenCalledWith(
        '/api/v1/desktop-control/grants/requests/11111111-2222-4333-8444-555555555555/deny',
        {
          method: 'POST',
          body: JSON.stringify({}),
        },
      );
    });
    expect(await screen.findByText('No pending approvals.')).toBeInTheDocument();
  });
});
