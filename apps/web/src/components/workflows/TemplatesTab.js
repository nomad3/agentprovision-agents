import React, { useState, useEffect } from 'react';
import { Card, Row, Col, Button, Badge, Spinner } from 'react-bootstrap';
import { FiDownload, FiEye } from 'react-icons/fi';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import dynamicWorkflowService from '../../services/dynamicWorkflowService';

const TRIGGER_LABELS = {
  cron: 'Scheduled', interval: 'Interval', webhook: 'Webhook',
  event: 'Event', manual: 'Manual', agent: 'Agent',
};

export default function TemplatesTab() {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const { t } = useTranslation('workflows');

  useEffect(() => {
    dynamicWorkflowService.browseTemplates()
      .then((data) => setTemplates(data || []))
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false));
  }, []);

  const handleInstall = async (templateId) => {
    try {
      const installed = await dynamicWorkflowService.installTemplate(templateId);
      navigate(`/workflows/builder/${installed.id}`);
    } catch (err) {
      console.error('Install failed:', err);
    }
  };

  if (loading) return <div className="text-center p-4"><Spinner /></div>;

  if (templates.length === 0) {
    return (
      <div className="text-center p-5 template-empty">
        <h5>{t('templates.noTemplates')}</h5>
        <p>{t('templates.noTemplatesDesc')}</p>
      </div>
    );
  }

  return (
    <Row xs={1} md={2} lg={3} className="g-3">
      {templates.map((tmpl) => (
        <Col key={tmpl.id}>
          <Card className="h-100 template-card">
            <Card.Body>
              <Card.Title style={{ fontSize: 14 }}>{tmpl.name}</Card.Title>
              <Card.Text className="card-text">
                {tmpl.description}
              </Card.Text>
              <div className="d-flex gap-1 flex-wrap">
                <Badge bg="secondary" style={{ fontSize: 10 }}>
                  {TRIGGER_LABELS[tmpl.trigger_config?.type] || 'Manual'}
                </Badge>
                <Badge bg="info" style={{ fontSize: 10 }}>
                  {t('templates.steps', { count: (tmpl.definition?.steps || []).length })}
                </Badge>
                <Badge bg="primary" style={{ fontSize: 10 }}>{tmpl.tier}</Badge>
              </div>
            </Card.Body>
            <Card.Footer className="card-footer d-flex gap-2">
              <Button variant="outline-primary" size="sm" onClick={() => handleInstall(tmpl.id)}>
                <FiDownload size={12} /> {t('templates.install')}
              </Button>
              <Button variant="outline-secondary" size="sm"
                onClick={() => navigate(`/workflows/builder/${tmpl.id}`)}>
                <FiEye size={12} /> {t('templates.preview')}
              </Button>
            </Card.Footer>
          </Card>
        </Col>
      ))}
    </Row>
  );
}
