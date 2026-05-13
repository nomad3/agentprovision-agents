import { useState, useEffect } from 'react';
import { Alert, Button, Card, Container, Form } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router-dom';
import authService from '../services/auth';
import BrandMark from '../components/BrandMark';

/**
 * Two-step password recovery.
 *
 *   stage = "request" — user lands on /reset-password fresh. They
 *           enter their email and we POST /auth/password-recovery/{email}.
 *           The backend always returns the same generic success message
 *           (no enumeration) and emails the token if the user exists.
 *
 *   stage = "confirm" — user followed a link from the email
 *           (`/reset-password?token=...&email=...`) OR clicked the
 *           "I already have a token" toggle. We show the token + new-
 *           password form and POST /auth/reset-password on submit.
 *
 * Earlier versions of this page only showed the confirm step, which
 * meant a user clicking "Forgot password?" from the login screen had
 * no path to actually GET the token — they got dropped onto a form
 * asking for one (see screenshot from 2026-05-12).
 */
const ResetPasswordPage = () => {
  const { t } = useTranslation('auth');
  const [searchParams] = useSearchParams();

  // Two stages; `tokenFromUrl` differentiates "user clicked the email
  // link" (auto-confirm) from "user toggled manually" (so the token
  // field stays editable when they typed it themselves).
  const [stage, setStage] = useState('request');
  const [tokenFromUrl, setTokenFromUrl] = useState(false);

  const [email, setEmail] = useState('');
  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const [error, setError] = useState('');
  const [requestSentMessage, setRequestSentMessage] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  // Hydrate from URL when the user lands via the email link. If we
  // have a token in the query string, jump straight to the confirm
  // stage so they don't have to re-enter their email.
  useEffect(() => {
    const tFromUrl = searchParams.get('token');
    const eFromUrl = searchParams.get('email');
    if (tFromUrl) {
      setToken(tFromUrl);
      setTokenFromUrl(true);
      setStage('confirm');
    }
    if (eFromUrl) setEmail(eFromUrl);
  }, [searchParams]);

  const handleRequest = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await authService.requestPasswordReset(email);
      // The backend returns the same generic message regardless of
      // whether the email exists (prevents enumeration). Echo that
      // back to the user verbatim — `reset.requestSent` resolves to
      // 'If an account exists for that email, a reset link has been
      // sent.' on both en + es.
      setRequestSentMessage(t('reset.requestSent'));
    } catch (err) {
      // 429 = rate-limited (slowapi 3/hour per IP). Surface a
      // friendlier message than the raw FastAPI 429 body.
      const status = err?.response?.status;
      if (status === 429) {
        setError(t('reset.rateLimited'));
      } else {
        setError(err?.response?.data?.detail || t('reset.requestError'));
      }
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async (e) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError(t('reset.mismatch'));
      return;
    }
    if (password.length < 8) {
      setError(t('reset.tooShort'));
      return;
    }

    setLoading(true);
    try {
      await authService.resetPassword(email, token, password);
      setSuccess(true);
    } catch (err) {
      setError(err?.response?.data?.detail || t('reset.error'));
    } finally {
      setLoading(false);
    }
  };

  // Toggle to the confirm stage when the user already has a token but
  // didn't land via the email link (e.g. someone gave them the token
  // out-of-band). Resets transient state so the form is clean.
  const switchToConfirm = () => {
    setStage('confirm');
    setRequestSentMessage('');
    setError('');
  };

  return (
    <Container className="d-flex justify-content-center align-items-center" style={{ minHeight: '100vh' }}>
      <Card style={{ width: '400px' }} className="shadow-lg p-4">
        <Card.Body>
          <div className="text-center mb-4">
            <div style={{ marginBottom: 16 }}><BrandMark /></div>
            <h2>{t('reset.title')}</h2>
          </div>

          {success ? (
            <div className="text-center">
              <Alert variant="success">{t('reset.success')}</Alert>
              <Link to="/login">
                <Button variant="primary" className="w-100">{t('login.title')}</Button>
              </Link>
            </div>
          ) : stage === 'request' ? (
            <>
              {error && <Alert variant="danger">{error}</Alert>}
              {requestSentMessage && (
                <Alert variant="success">{requestSentMessage}</Alert>
              )}
              <p className="text-muted small">{t('reset.requestIntro')}</p>
              <Form onSubmit={handleRequest}>
                <Form.Group className="mb-3">
                  <Form.Label>{t('reset.email')}</Form.Label>
                  <Form.Control
                    type="email"
                    placeholder={t('reset.emailPlaceholder')}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </Form.Group>

                <Button
                  variant="primary"
                  type="submit"
                  className="w-100 mb-2"
                  disabled={loading}
                >
                  {loading ? t('reset.processing') : t('reset.sendLink')}
                </Button>
              </Form>
              {/* Out-of-band path: user already has a token (admin
                  copy-pasted it, or they grabbed it from a previous
                  email). Toggle to the confirm form without firing a
                  duplicate email request. */}
              <div className="text-center mt-3">
                <Button
                  variant="link"
                  size="sm"
                  className="text-muted p-0"
                  onClick={switchToConfirm}
                >
                  {t('reset.haveTokenLink')}
                </Button>
              </div>
              <div className="text-center mt-2">
                <Link to="/login">{t('register.loginLink')}</Link>
              </div>
            </>
          ) : (
            <>
              {error && <Alert variant="danger">{error}</Alert>}
              <p className="text-muted small">{t('reset.confirmIntro')}</p>
              <Form onSubmit={handleConfirm}>
                <Form.Group className="mb-3">
                  <Form.Label>{t('reset.email')}</Form.Label>
                  <Form.Control
                    type="email"
                    placeholder={t('reset.emailPlaceholder')}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                  />
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>{t('reset.token')}</Form.Label>
                  <Form.Control
                    type="text"
                    placeholder={t('reset.tokenPlaceholder')}
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    readOnly={tokenFromUrl}
                    required
                  />
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>{t('reset.newPassword')}</Form.Label>
                  <Form.Control
                    type="password"
                    placeholder={t('reset.newPasswordPlaceholder')}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                  />
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>{t('reset.confirmPassword')}</Form.Label>
                  <Form.Control
                    type="password"
                    placeholder={t('reset.confirmPasswordPlaceholder')}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    required
                  />
                </Form.Group>

                <Button
                  variant="primary"
                  type="submit"
                  className="w-100 mb-2"
                  disabled={loading}
                >
                  {loading ? t('reset.processing') : t('reset.submit')}
                </Button>
                <div className="text-center mt-3">
                  <Link to="/login">{t('register.loginLink')}</Link>
                </div>
              </Form>
            </>
          )}
        </Card.Body>
      </Card>
    </Container>
  );
};

export default ResetPasswordPage;
