/**
 * /login/device — the user-facing landing page for the alpha CLI's
 * device-auth flow.
 *
 * Flow:
 *   1. `alpha login` from the CLI calls POST /api/v1/auth/device-code,
 *      which returns a `user_code` (XXXX-XXXX) plus a verification URL
 *      pointing at this page (`/login/device?user_code=XXXX-XXXX`).
 *   2. The user opens that URL in a browser. This page reads the
 *      `user_code` from the query string, shows it prominently, and
 *      asks them to confirm.
 *   3. On click "Approve", the page POSTs the `user_code` to
 *      `/api/v1/auth/device-approve`. The server binds a fresh access
 *      token to the device_code so the CLI's polling /device-token call
 *      succeeds on the next tick.
 *
 * Auth: the approve endpoint requires `current_user`, so the user MUST
 * be logged in. Wrapped in `<ProtectedRoute>` at the App.js route
 * registration — unauthenticated users get redirected to /login with a
 * return-to that brings them back here after sign-in.
 *
 * Why this page existed-as-a-404 until now: the CLI's device-flow
 * server endpoint was shipped without a matching SPA route. The api
 * returned a valid `/login/device?user_code=...` URL, the CLI printed
 * it, and the user hit a React Router 404 every time. Filed as the
 * follow-up to the cli-v0.7.4 release.
 */
import { useEffect, useState } from 'react';
import { Alert, Button, Card, Container, Spinner } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import axios from 'axios';

import { useAuth } from '../App';
import BrandMark from '../components/BrandMark';

// Match the server-side canonical user_code regex (XXXX-XXXX, uppercase
// alphanumeric). Server still re-normalises on its end (strips spaces +
// dashes, uppercases) — this check is just for the obvious-typo case so
// we don't fire a POST that the server will 400.
const USER_CODE_RE = /^[A-Z0-9]{4}-[A-Z0-9]{4}$/;

const DeviceLoginPage = () => {
  const { t } = useTranslation('auth');
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  // Normalise the query-string value the same way the server does, so
  // a paste-from-screenshot with lowercase / extra spaces still renders
  // a canonical XXXX-XXXX code in the UI.
  const rawCode = searchParams.get('user_code') || '';
  const normalised = rawCode.replace(/\s+/g, '').replace(/-/g, '').toUpperCase();
  const userCode =
    normalised.length === 8 ? `${normalised.slice(0, 4)}-${normalised.slice(4)}` : rawCode;

  const [status, setStatus] = useState('idle'); // idle | submitting | approved | error
  const [errorMsg, setErrorMsg] = useState('');

  // Pre-flight: if the URL is missing the user_code or it's malformed,
  // skip straight to the error state so the user sees a clear "the
  // link from your terminal is broken" instead of POSTing and getting
  // a server 400.
  useEffect(() => {
    if (!userCode) {
      setStatus('error');
      setErrorMsg(t('device.error.missingCode', 'No user_code in URL — copy the link from your terminal again.'));
    } else if (!USER_CODE_RE.test(userCode)) {
      setStatus('error');
      setErrorMsg(t('device.error.badFormat', 'Code "{{code}}" is not in the expected XXXX-XXXX format.', { code: userCode }));
    }
    // run once on mount; userCode is stable per pathname load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleApprove = async () => {
    setStatus('submitting');
    setErrorMsg('');
    try {
      await axios.post('/api/v1/auth/device-approve', { user_code: userCode });
      setStatus('approved');
    } catch (err) {
      const code = err?.response?.status;
      const detail = err?.response?.data?.detail;
      // Map known server statuses to actionable messages. The fallback
      // surfaces the raw detail so a copy-paste to a bug report keeps
      // signal — better than swallowing it under "Something went wrong".
      if (code === 404) {
        setErrorMsg(t('device.error.notFound', 'This code has expired or was never issued. Run `alpha login` again in your terminal.'));
      } else if (code === 409) {
        setErrorMsg(t('device.error.alreadyApproved', 'This code was already approved. If your CLI is still waiting, run `alpha login` to get a fresh code.'));
      } else if (code === 400) {
        setErrorMsg(t('device.error.invalid', detail || 'Code format invalid.'));
      } else {
        setErrorMsg(detail || err?.message || t('device.error.generic', 'Approval failed.'));
      }
      setStatus('error');
    }
  };

  return (
    <Container className="d-flex align-items-center justify-content-center py-5" style={{ minHeight: '80vh' }}>
      <Card className="shadow-sm" style={{ maxWidth: 520, width: '100%' }}>
        <Card.Body className="p-4">
          <div className="text-center mb-4">
            <BrandMark />
          </div>
          <h1 className="h4 mb-3 text-center">
            {t('device.title', 'Approve alpha CLI sign-in')}
          </h1>
          <p className="text-muted text-center small mb-4">
            {t('device.subtitle', 'Confirm the code your terminal printed matches the one below.')}
          </p>

          {status !== 'approved' && status !== 'error' && (
            <>
              <div className="bg-light rounded p-3 text-center mb-4">
                <div className="text-muted small mb-1">
                  {t('device.codeLabel', 'Verification code')}
                </div>
                <div
                  className="display-6 font-monospace fw-bold"
                  style={{ letterSpacing: '0.15em' }}
                  data-testid="device-user-code"
                >
                  {userCode || '— — — —'}
                </div>
              </div>
              <p className="small text-muted">
                {t('device.signedInAs', 'You are signed in as')}{' '}
                <strong>{user?.email || '(loading…)'}</strong>.
                {' '}
                {t('device.scope', 'Approving links a session token to the terminal that requested this code.')}
              </p>
              <div className="d-grid gap-2 mt-3">
                <Button
                  variant="primary"
                  size="lg"
                  onClick={handleApprove}
                  disabled={status === 'submitting'}
                >
                  {status === 'submitting' ? (
                    <>
                      <Spinner as="span" animation="border" size="sm" className="me-2" />
                      {t('device.approving', 'Approving…')}
                    </>
                  ) : (
                    t('device.approve', 'Approve sign-in')
                  )}
                </Button>
                <Link to="/dashboard" className="btn btn-link">
                  {t('device.cancel', 'Cancel and return to dashboard')}
                </Link>
              </div>
            </>
          )}

          {status === 'approved' && (
            <Alert variant="success" className="mb-0">
              <Alert.Heading className="h6">
                {t('device.success.title', 'Approved.')}
              </Alert.Heading>
              <p className="mb-0 small">
                {t('device.success.body', 'Return to your terminal. The CLI will finish signing in within a few seconds.')}
              </p>
            </Alert>
          )}

          {status === 'error' && (
            <Alert variant="danger" className="mb-0" data-testid="device-error">
              <Alert.Heading className="h6">
                {t('device.error.title', 'Could not approve sign-in')}
              </Alert.Heading>
              <p className="mb-2 small">{errorMsg}</p>
              <Link to="/dashboard" className="btn btn-sm btn-outline-secondary">
                {t('device.error.back', 'Back to dashboard')}
              </Link>
            </Alert>
          )}
        </Card.Body>
      </Card>
    </Container>
  );
};

export default DeviceLoginPage;
