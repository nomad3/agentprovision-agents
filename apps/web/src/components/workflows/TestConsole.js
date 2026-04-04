import React from 'react';
import { Badge, Alert, ListGroup, Spinner } from 'react-bootstrap';
import { FiX, FiCheckCircle, FiAlertCircle } from 'react-icons/fi';
import { useTranslation } from 'react-i18next';

export default function TestConsole({ results, onClose }) {
  const { t } = useTranslation('workflows');

  if (!results) {
    return (
      <div className="test-console">
        <div className="test-console-header">
          <span style={{ fontWeight: 600 }}>{t('builder.testConsole.title')}</span>
          <FiX onClick={onClose} style={{ cursor: 'pointer' }} />
        </div>
        <div className="test-console-loading">
          <Spinner size="sm" /> {t('builder.testConsole.running')}
        </div>
      </div>
    );
  }

  const hasErrors = results.validation_errors?.length > 0;

  return (
    <div className="test-console">
      <div className="test-console-header">
        <span style={{ fontWeight: 600 }}>{t('builder.testConsole.title')}</span>
        <Badge bg={hasErrors ? 'danger' : 'success'}>
          {hasErrors ? t('builder.testConsole.errorsFound') : t('builder.testConsole.valid')}
        </Badge>
        <FiX onClick={onClose} style={{ cursor: 'pointer', marginLeft: 'auto' }} />
      </div>
      <div className="test-console-body">
        {hasErrors && (
          <Alert variant="danger" style={{ fontSize: 12, padding: 8 }}>
            {results.validation_errors.map((err, i) => (
              <div key={i}><FiAlertCircle /> {err}</div>
            ))}
          </Alert>
        )}

        <h6 className="test-console-plan-title">
          {t('builder.testConsole.executionPlan')} ({t('builder.testConsole.steps', { count: results.step_count || 0 })})
        </h6>
        <ListGroup variant="flush">
          {(results.steps_planned || []).map((step, i) => (
            <ListGroup.Item key={i} className="test-console-step-item">
              <Badge bg="secondary" style={{ fontSize: 10 }}>{i + 1}</Badge>
              <span>{typeof step === 'string' ? step : (step.type || JSON.stringify(step))}</span>
              <FiCheckCircle style={{ color: '#22c55e', marginLeft: 'auto' }} size={12} />
            </ListGroup.Item>
          ))}
        </ListGroup>

        {results.integrations_required?.length > 0 && (
          <div className="test-console-integrations">
            <h6>{t('builder.testConsole.requiredIntegrations')}</h6>
            {results.integrations_required.map((int, i) => (
              <Badge key={i} bg="outline-secondary" className="badge">
                {int}
              </Badge>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
