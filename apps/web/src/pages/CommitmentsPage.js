import React, { useState, useEffect } from 'react';
import { Badge, Card, Button } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { FaShieldAlt, FaFlag, FaBookOpen, FaSearch } from 'react-icons/fa';
import Layout from '../components/Layout';
import { EmptyState, LoadingSpinner, useToast } from '../components/common';
import commitmentService from '../services/commitments';

// Typed commitment statuses — shared vocabulary across chat / trace / UI
// (plan 2026-06-08 §12). Keep this list aligned with CommitmentState.
const STATE_VARIANT = {
  open: 'secondary',
  in_progress: 'info',
  blocked: 'warning',
  at_risk: 'warning',
  done: 'success',
  fulfilled: 'success',
  renegotiated: 'secondary',
  failed: 'danger',
  broken: 'danger',
};

// Red-flag severity ladder (watch < warn < escalate < block).
const LEVEL_VARIANT = {
  watch: 'secondary',
  warn: 'warning',
  escalate: 'danger',
  block: 'dark',
};

const QUALITY_VARIANT = {
  succeeded: 'success',
  partially_succeeded: 'warning',
  failed: 'danger',
  inconclusive: 'secondary',
};

const unwrap = (resp) => {
  const d = resp && resp.data !== undefined ? resp.data : resp;
  return Array.isArray(d) ? d : [];
};

const isProofMissing = (c) =>
  (c.proof_required || []).length > 0 && (c.proof_refs || []).length === 0;

const CommitmentsPage = () => {
  const { t } = useTranslation('commitments');
  const toast = useToast();
  const [commitments, setCommitments] = useState([]);
  const [redFlags, setRedFlags] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({});

  const load = async () => {
    try {
      setLoading(true);
      const [openResp, flagResp, artifactResp] = await Promise.all([
        commitmentService.listOpen(),
        commitmentService.listRedFlags(),
        commitmentService.listLearningArtifacts(),
      ]);
      setCommitments(unwrap(openResp));
      setRedFlags(unwrap(flagResp));
      setArtifacts(unwrap(artifactResp));
    } catch (err) {
      console.error('Error loading accountability surface:', err);
      toast.error(t('errors.load', 'Could not load commitments'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggle = (id) => setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  const titleFor = (commitmentId) => {
    const match = commitments.find((c) => String(c.id) === String(commitmentId));
    return match ? match.title : commitmentId;
  };

  const renderBadge = (value, map) => (
    <Badge bg={map[value] || 'secondary'} className="text-uppercase">{value}</Badge>
  );

  const empty =
    !loading && commitments.length === 0 && redFlags.length === 0 && artifacts.length === 0;

  return (
    <Layout>
      <div className="container-fluid py-4" style={{ maxWidth: 1100 }}>
        <div className="d-flex align-items-center gap-2 mb-1">
          <FaShieldAlt style={{ color: 'var(--brand-primary, #4f8cff)' }} />
          <h2 className="mb-0">{t('title', 'Accountability')}</h2>
        </div>
        <p className="text-muted">
          {t('subtitle', 'What Luna promised, what is at risk, and what we learned — grounded in proof.')}
        </p>

        {loading && <LoadingSpinner text={t('loading', 'Loading commitments…')} />}

        {empty && (
          <EmptyState
            title={t('empty.title', 'No open commitments')}
            description={t('empty.description', 'When Luna commits to an outcome it shows up here with its proof requirements.')}
          />
        )}

        {/* ── At risk (red flags) ─────────────────────────────────────── */}
        {redFlags.length > 0 && (
          <section className="mb-4">
            <h5 className="d-flex align-items-center gap-2">
              <FaFlag className="text-danger" /> {t('redFlags.heading', 'At risk')}
            </h5>
            {redFlags.map((f) => (
              <Card key={f.commitment_id} className="mb-2 border-warning">
                <Card.Body className="py-2">
                  <div className="d-flex justify-content-between align-items-start gap-2">
                    <div>
                      {renderBadge(f.level, LEVEL_VARIANT)}{' '}
                      <strong>{titleFor(f.commitment_id)}</strong>
                      <div className="text-muted small mt-1">{f.risk}</div>
                    </div>
                    <Button
                      size="sm"
                      variant="outline-secondary"
                      data-testid={`inspect-redflag-${f.commitment_id}`}
                      onClick={() => toggle(`flag-${f.commitment_id}`)}
                    >
                      <FaSearch className="me-1" />
                      {t('redFlags.why', 'Why?')}
                    </Button>
                  </div>
                  {expanded[`flag-${f.commitment_id}`] && (
                    <div className="mt-2 small">
                      <div><strong>{t('redFlags.risk', 'Risk')}:</strong> {f.risk}</div>
                      {f.evidence && (
                        <div><strong>{t('redFlags.evidence', 'Evidence')}:</strong> {f.evidence}</div>
                      )}
                      <div><strong>{t('redFlags.decision', 'Decision needed')}:</strong> {f.decision_needed}</div>
                      {f.recommended_next_action && (
                        <div><strong>{t('redFlags.next', 'Recommended next')}:</strong> {f.recommended_next_action}</div>
                      )}
                      {(f.missing || []).length > 0 && (
                        <div>
                          <strong>{t('redFlags.missing', 'Missing proof')}:</strong>{' '}
                          {(f.missing || []).map((m) => (
                            <Badge key={m} bg="light" text="dark" className="me-1">{m}</Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </Card.Body>
              </Card>
            ))}
          </section>
        )}

        {/* ── Open commitments ────────────────────────────────────────── */}
        {commitments.length > 0 && (
          <section className="mb-4">
            <h5 className="d-flex align-items-center gap-2">
              <FaShieldAlt className="text-info" /> {t('open.heading', 'Open commitments')}
            </h5>
            {commitments.map((c) => (
              <Card key={c.id} className="mb-2">
                <Card.Body className="py-2">
                  <div className="d-flex justify-content-between align-items-start gap-2">
                    <div>
                      <strong>{c.title}</strong>
                      <div className="mt-1 d-flex flex-wrap gap-1 align-items-center">
                        {renderBadge(c.state, STATE_VARIANT)}
                        {c.owner_agent_slug && (
                          <span className="text-muted small">@{c.owner_agent_slug}</span>
                        )}
                        {c.risk_threshold && (
                          <Badge bg="light" text="dark">risk: {c.risk_threshold}</Badge>
                        )}
                        {isProofMissing(c) && (
                          <Badge bg="danger" data-testid={`proof-missing-${c.id}`}>
                            {t('open.proofMissing', 'Proof missing')}
                          </Badge>
                        )}
                      </div>
                      {(c.proof_required || []).length > 0 && (
                        <div className="text-muted small mt-1">
                          {t('open.proofNeeded', 'Proof needed')}:{' '}
                          {(c.proof_required || []).join(', ')}
                        </div>
                      )}
                    </div>
                  </div>
                </Card.Body>
              </Card>
            ))}
          </section>
        )}

        {/* ── Recent learning ─────────────────────────────────────────── */}
        {artifacts.length > 0 && (
          <section className="mb-4">
            <h5 className="d-flex align-items-center gap-2">
              <FaBookOpen className="text-secondary" /> {t('learning.heading', 'Recent learning')}
            </h5>
            {artifacts.map((a) => (
              <Card key={a.artifact_id} className="mb-2">
                <Card.Body className="py-2">
                  <div className="d-flex justify-content-between align-items-start gap-2">
                    <div>
                      <div>{a.task_summary}</div>
                      <div className="mt-1 d-flex flex-wrap gap-1 align-items-center">
                        {renderBadge(a.outcome_quality, QUALITY_VARIANT)}
                        {a.memory_write_recommendation && a.memory_write_recommendation !== 'none' && (
                          <Badge bg="light" text="dark">{a.memory_write_recommendation}</Badge>
                        )}
                      </div>
                      {(a.failed_assumptions || []).length > 0 && (
                        <ul className="text-muted small mt-1 mb-0">
                          {(a.failed_assumptions || []).map((fa, i) => (
                            <li key={i}>{fa}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </div>
                </Card.Body>
              </Card>
            ))}
          </section>
        )}
      </div>
    </Layout>
  );
};

export default CommitmentsPage;
