import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Modal,
  Spinner,
  Stack,
} from 'react-bootstrap';
import valuesService from '../../services/values';

// Operator-facing value-set editor for the Luna Value Layer (#647).
// Mounts inside AgentDetailPage as the "Values" tab.
//
// Three named lists (protect/pursue/avoid) edited in-place. Save writes a
// new append-only version. The "Open break-glass" modal opens a
// time-boxed override (1h default, 24h max) for incident response.
//
// Break-glass active banner: when the most-recent version has
// expires_at set + still in the future, surface a yellow banner with
// who opened it + when it expires.

const EMPTY = { slug: '', description: '' };

const ListEditor = ({ title, items, color, onChange }) => {
  const update = (idx, field, value) => {
    const next = items.slice();
    next[idx] = { ...next[idx], [field]: value };
    onChange(next);
  };
  const remove = (idx) => {
    const next = items.slice();
    next.splice(idx, 1);
    onChange(next);
  };
  const add = () => onChange([...items, { ...EMPTY }]);

  return (
    <Card className="mb-3">
      <Card.Header className="d-flex align-items-center justify-content-between">
        <strong>
          <Badge bg={color} className="me-2">{items.length}</Badge>
          {title}
        </strong>
        <Button size="sm" variant="outline-primary" onClick={add}>
          + Add
        </Button>
      </Card.Header>
      <Card.Body>
        {items.length === 0 && (
          <p className="text-muted small mb-0">No {title.toLowerCase()} items.</p>
        )}
        {items.map((item, idx) => (
          <Stack direction="horizontal" gap={2} key={idx} className="mb-2 align-items-start">
            <Form.Control
              placeholder="slug (e.g. production-main)"
              value={item.slug || ''}
              onChange={(e) => update(idx, 'slug', e.target.value)}
              style={{ maxWidth: '240px' }}
              maxLength={80}
            />
            <Form.Control
              placeholder="description (operator-visible reason)"
              value={item.description || ''}
              onChange={(e) => update(idx, 'description', e.target.value)}
              maxLength={400}
            />
            <Button
              size="sm"
              variant="outline-danger"
              onClick={() => remove(idx)}
              aria-label={`remove ${item.slug || 'item'}`}
            >
              ×
            </Button>
          </Stack>
        ))}
      </Card.Body>
    </Card>
  );
};

const BreakGlassBanner = ({ valueSet }) => {
  if (!valueSet?.expires_at) return null;
  const expiresAtMs = Date.parse(valueSet.expires_at);
  if (Number.isNaN(expiresAtMs)) return null;
  const stillActive = expiresAtMs > Date.now();
  if (!stillActive) return null;

  return (
    <Alert variant="warning" className="mb-3">
      <Alert.Heading className="h6">
        Break-glass override active
      </Alert.Heading>
      <div className="small">
        Opened by operator <code>{valueSet.break_glass_operator_id || '(unknown)'}</code>.
        Expires at <strong>{new Date(expiresAtMs).toLocaleString()}</strong>.
        {valueSet.break_glass_reason && (
          <>
            {' '}Reason: <em>{valueSet.break_glass_reason}</em>.
          </>
        )}
      </div>
      <div className="small text-muted mt-1">
        Until expiry, the protect/avoid items below are the relaxed set.
        After expiry, the prior ordinary version automatically takes over —
        no action needed.
      </div>
    </Alert>
  );
};

const BreakGlassModal = ({ show, onClose, valueSet, onSubmit, submitting }) => {
  const [reason, setReason] = useState('');
  const [hours, setHours] = useState(1);
  const [keepProtect, setKeepProtect] = useState({});
  const [keepAvoid, setKeepAvoid] = useState({});

  // Reset on open
  useEffect(() => {
    if (show) {
      setReason('');
      setHours(1);
      setKeepProtect({});
      setKeepAvoid({});
    }
  }, [show]);

  const submit = (e) => {
    e.preventDefault();
    const keepProtectSlugs = Object.keys(keepProtect).filter((k) => keepProtect[k]);
    const keepAvoidSlugs = Object.keys(keepAvoid).filter((k) => keepAvoid[k]);
    const durationSeconds = Math.max(60, Math.min(24 * 3600, Math.round(hours * 3600)));
    onSubmit({
      reason: reason.trim(),
      duration_seconds: durationSeconds,
      keep_protect_slugs: keepProtectSlugs,
      keep_avoid_slugs: keepAvoidSlugs,
    });
  };

  return (
    <Modal show={show} onHide={onClose} centered size="lg">
      <Form onSubmit={submit}>
        <Modal.Header closeButton>
          <Modal.Title>Open break-glass</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Alert variant="info" className="small">
            A break-glass override writes a new value-set version with the
            protect/avoid items you DROP. The override auto-expires after the
            chosen duration — no follow-up cleanup needed.
            One audit-log entry is recorded per use.
          </Alert>
          <Form.Group className="mb-3">
            <Form.Label>Reason <span className="text-danger">*</span></Form.Label>
            <Form.Control
              as="textarea"
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={500}
              required
              placeholder="e.g. production incident #1234"
            />
          </Form.Group>
          <Form.Group className="mb-3">
            <Form.Label>Duration (hours)</Form.Label>
            <Form.Control
              type="number"
              min={0.02} max={24} step={0.5}
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
            />
            <Form.Text className="text-muted">
              Min ~1min, max 24h. Default 1h.
            </Form.Text>
          </Form.Group>
          {valueSet?.protect?.length > 0 && (
            <Form.Group className="mb-3">
              <Form.Label>Keep these protect items</Form.Label>
              <div className="small text-muted mb-1">
                Unchecked items are DROPPED for the duration.
              </div>
              {valueSet.protect.map((item) => (
                <Form.Check
                  key={item.slug}
                  type="checkbox"
                  id={`keep-protect-${item.slug}`}
                  label={<><code>{item.slug}</code> — {item.description}</>}
                  checked={!!keepProtect[item.slug]}
                  onChange={(e) =>
                    setKeepProtect({ ...keepProtect, [item.slug]: e.target.checked })
                  }
                />
              ))}
            </Form.Group>
          )}
          {valueSet?.avoid?.length > 0 && (
            <Form.Group className="mb-3">
              <Form.Label>Keep these avoid items</Form.Label>
              {valueSet.avoid.map((item) => (
                <Form.Check
                  key={item.slug}
                  type="checkbox"
                  id={`keep-avoid-${item.slug}`}
                  label={<><code>{item.slug}</code> — {item.description}</>}
                  checked={!!keepAvoid[item.slug]}
                  onChange={(e) =>
                    setKeepAvoid({ ...keepAvoid, [item.slug]: e.target.checked })
                  }
                />
              ))}
            </Form.Group>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="warning"
            type="submit"
            disabled={!reason.trim() || submitting}
          >
            {submitting ? 'Opening…' : 'Open break-glass'}
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
};

const ValueSetTabSection = ({ agentId }) => {
  const [valueSet, setValueSet] = useState(null);
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [info, setInfo] = useState(null);
  const [showBreakGlass, setShowBreakGlass] = useState(false);
  const [breakGlassSubmitting, setBreakGlassSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await valuesService.getForAgent(agentId);
      setValueSet(res.data);
      setDraft({
        protect: res.data.protect.map((i) => ({ slug: i.slug, description: i.description })),
        pursue: res.data.pursue.map((i) => ({ slug: i.slug, description: i.description })),
        avoid: res.data.avoid.map((i) => ({ slug: i.slug, description: i.description })),
      });
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Failed to load values');
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    if (agentId) load();
  }, [agentId, load]);

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      // Drop blank-slug items before posting; the API rejects them but
      // surfacing locally is faster feedback.
      const clean = {
        protect: draft.protect.filter((i) => i.slug?.trim()),
        pursue: draft.pursue.filter((i) => i.slug?.trim()),
        avoid: draft.avoid.filter((i) => i.slug?.trim()),
      };
      const res = await valuesService.putForAgent(agentId, clean);
      setValueSet(res.data);
      setInfo(`Saved version ${res.data.version}`);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleBreakGlass = async (body) => {
    setBreakGlassSubmitting(true);
    setError(null);
    setInfo(null);
    try {
      const res = await valuesService.breakGlassForAgent(agentId, body);
      setValueSet(res.data);
      setDraft({
        protect: res.data.protect.map((i) => ({ slug: i.slug, description: i.description })),
        pursue: res.data.pursue.map((i) => ({ slug: i.slug, description: i.description })),
        avoid: res.data.avoid.map((i) => ({ slug: i.slug, description: i.description })),
      });
      setShowBreakGlass(false);
      setInfo(
        `Break-glass opened — version ${res.data.version}, expires ` +
          new Date(res.data.expires_at).toLocaleString()
      );
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Break-glass failed');
    } finally {
      setBreakGlassSubmitting(false);
    }
  };

  const hasChanges = useMemo(() => {
    if (!valueSet || !draft) return false;
    return JSON.stringify(draft) !== JSON.stringify({
      protect: valueSet.protect.map((i) => ({ slug: i.slug, description: i.description })),
      pursue: valueSet.pursue.map((i) => ({ slug: i.slug, description: i.description })),
      avoid: valueSet.avoid.map((i) => ({ slug: i.slug, description: i.description })),
    });
  }, [valueSet, draft]);

  if (loading) {
    return (
      <div className="p-4 text-center">
        <Spinner animation="border" size="sm" /> Loading value set…
      </div>
    );
  }

  return (
    <div>
      <BreakGlassBanner valueSet={valueSet} />

      <div className="d-flex align-items-center justify-content-between mb-3">
        <div>
          <strong>Value set</strong>{' '}
          <Badge bg="secondary">version {valueSet?.version ?? '—'}</Badge>{' '}
          <small className="text-muted">
            updated {valueSet?.updated_at ? new Date(valueSet.updated_at).toLocaleString() : 'never'}
          </small>
        </div>
        <div>
          <Button
            variant="outline-warning"
            size="sm"
            className="me-2"
            onClick={() => setShowBreakGlass(true)}
          >
            Open break-glass
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSave}
            disabled={!hasChanges || saving}
          >
            {saving ? 'Saving…' : 'Save (new version)'}
          </Button>
        </div>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}
      {info && <Alert variant="success">{info}</Alert>}

      <Alert variant="light" className="small mb-3">
        <strong>protect</strong> — actions on these get blocked (mutation) or warned (mention).{' '}
        <strong>pursue</strong> — surfacing these in chat amplifies positive affect (1.5x).{' '}
        <strong>avoid</strong> — Luna gets a soft warning, no block.{' '}
        Empty value set = nothing is enforced. Kill-switch is per-tenant on the backend.
      </Alert>

      {draft && (
        <>
          <ListEditor
            title="Protect"
            color="danger"
            items={draft.protect}
            onChange={(items) => setDraft({ ...draft, protect: items })}
          />
          <ListEditor
            title="Pursue"
            color="success"
            items={draft.pursue}
            onChange={(items) => setDraft({ ...draft, pursue: items })}
          />
          <ListEditor
            title="Avoid"
            color="warning"
            items={draft.avoid}
            onChange={(items) => setDraft({ ...draft, avoid: items })}
          />
        </>
      )}

      <BreakGlassModal
        show={showBreakGlass}
        onClose={() => setShowBreakGlass(false)}
        valueSet={valueSet}
        onSubmit={handleBreakGlass}
        submitting={breakGlassSubmitting}
      />
    </div>
  );
};

export default ValueSetTabSection;
