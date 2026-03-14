import React, { useState, useEffect, useCallback } from 'react';
import { Container, Row, Col, Card, Form, Button, Badge, Alert, Spinner } from 'react-bootstrap';
import { FaRobot, FaGoogle, FaKey, FaSave, FaCheck, FaEye, FaEyeSlash } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import api from '../services/api';

const PROVIDER_ICONS = {
  anthropic_llm: FaRobot,
  gemini_llm: FaGoogle,
};

const LLM_PROVIDER_SUFFIX = '_llm';

export default function LLMSettingsPage() {
  const { t } = useTranslation('common');
  const [providers, setProviders] = useState([]);
  const [credentials, setCredentials] = useState({});
  const [activeProvider, setActiveProvider] = useState('gemini_llm');
  const [showKeys, setShowKeys] = useState({});
  const [saving, setSaving] = useState({});
  const [saveSuccess, setSaveSuccess] = useState({});
  const [activating, setActivating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      // Load registry entries filtered to LLM providers
      const registryRes = await api.get('/integration_configs/registry');
      const llmProviders = registryRes.data.filter(e => e.integration_name.endsWith(LLM_PROVIDER_SUFFIX));

      // Load tenant's integration configs to check which have credentials
      const configsRes = await api.get('/integration_configs');
      const configMap = {};
      configsRes.data.forEach(c => { configMap[c.integration_name] = c; });

      // Load tenant features to get active provider
      const featuresRes = await api.get('/features');
      const active = featuresRes.data?.active_llm_provider || 'gemini_llm';

      // For each LLM provider, check credential status
      const providersWithStatus = await Promise.all(llmProviders.map(async (p) => {
        const config = configMap[p.integration_name];
        let credStatus = {};
        if (config) {
          try {
            const statusRes = await api.get(`/integration_configs/${config.id}/credentials/status`);
            (statusRes.data.stored_keys || []).forEach(key => { credStatus[key] = true; });
          } catch { /* no creds yet */ }
        }
        return { ...p, config, credStatus, configured: Object.keys(credStatus).length > 0, name: p.integration_name };
      }));

      setProviders(providersWithStatus);
      setActiveProvider(active);
      setError(null);
    } catch (err) {
      setError(err.message || 'Failed to load LLM providers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleCredentialChange = (providerName, key, value) => {
    setCredentials(prev => ({
      ...prev,
      [providerName]: { ...(prev[providerName] || {}), [key]: value }
    }));
  };

  const handleSave = async (provider) => {
    const creds = credentials[provider.name];
    if (!creds) return;

    setSaving(prev => ({ ...prev, [provider.name]: true }));
    try {
      // Ensure integration config exists
      let configId = provider.config?.id;
      if (!configId) {
        const createRes = await api.post('/integration_configs', {
          integration_name: provider.name,
          enabled: true,
        });
        configId = createRes.data.id;
      }

      // Store each credential field
      for (const [key, value] of Object.entries(creds)) {
        if (value && value.trim()) {
          await api.post(`/integration_configs/${configId}/credentials`, {
            credential_key: key,
            value: value.trim(),
            credential_type: key === 'api_key' ? 'api_key' : 'config',
          });
        }
      }

      setSaveSuccess(prev => ({ ...prev, [provider.name]: true }));
      setCredentials(prev => ({ ...prev, [provider.name]: {} }));
      setTimeout(() => setSaveSuccess(prev => ({ ...prev, [provider.name]: false })), 3000);
      await loadData();
    } catch (err) {
      setError(`Failed to save ${provider.display_name} credentials: ${err.message}`);
    } finally {
      setSaving(prev => ({ ...prev, [provider.name]: false }));
    }
  };

  const handleSetActive = async (providerName) => {
    setActivating(true);
    try {
      await api.put('/features', { active_llm_provider: providerName });
      setActiveProvider(providerName);
    } catch (err) {
      setError(`Failed to set active provider: ${err.message}`);
    } finally {
      setActivating(false);
    }
  };

  if (loading) {
    return (
      <Container className="py-4 text-center">
        <Spinner animation="border" className="text-info" />
        <p className="text-light mt-2">{t('loading', 'Loading...')}</p>
      </Container>
    );
  }

  return (
    <Container fluid className="py-4">
      <h2 className="text-light mb-1">{t('llm.title', 'LLM Providers')}</h2>
      <p className="text-secondary mb-4">{t('llm.subtitle', 'Configure which AI model powers your agent chat')}</p>

      {error && <Alert variant="danger" dismissible onClose={() => setError(null)}>{error}</Alert>}

      <Row xs={1} md={2} lg={3} className="g-4">
        {providers.map(provider => {
          const Icon = PROVIDER_ICONS[provider.name] || FaKey;
          const isActive = activeProvider === provider.name;
          const providerCreds = credentials[provider.name] || {};

          return (
            <Col key={provider.name}>
              <Card className="h-100" style={{
                background: 'rgba(255,255,255,0.05)',
                border: isActive ? '1px solid rgba(0, 210, 255, 0.5)' : '1px solid rgba(255,255,255,0.1)',
                borderRadius: '12px',
              }}>
                <Card.Body>
                  <div className="d-flex justify-content-between align-items-center mb-3">
                    <div className="d-flex align-items-center gap-2">
                      <Icon size={24} className="text-info" />
                      <h5 className="text-light mb-0">{provider.display_name}</h5>
                    </div>
                    <div className="d-flex gap-2">
                      {provider.configured && (
                        <Badge bg="success" className="px-2 py-1">
                          {t('llm.configured', 'Configured')}
                        </Badge>
                      )}
                      {isActive && (
                        <Badge bg="info" className="px-2 py-1">
                          {t('llm.active', 'Active')}
                        </Badge>
                      )}
                    </div>
                  </div>

                  <p className="text-secondary small mb-3">{provider.description}</p>

                  {(provider.credentials || []).map(cred => (
                    <Form.Group key={cred.key} className="mb-2">
                      <Form.Label className="text-light small">{cred.label}</Form.Label>
                      <div className="d-flex gap-2">
                        <Form.Control
                          type={cred.type === 'password' && !showKeys[`${provider.name}_${cred.key}`] ? 'password' : 'text'}
                          size="sm"
                          placeholder={provider.credStatus[cred.key] ? t('llm.keyMasked', 'Saved (enter new value to update)') : cred.help || ''}
                          value={providerCreds[cred.key] || ''}
                          onChange={e => handleCredentialChange(provider.name, cred.key, e.target.value)}
                          style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', color: '#fff' }}
                        />
                        {cred.type === 'password' && (
                          <Button
                            variant="outline-secondary"
                            size="sm"
                            onClick={() => setShowKeys(prev => ({
                              ...prev,
                              [`${provider.name}_${cred.key}`]: !prev[`${provider.name}_${cred.key}`]
                            }))}
                          >
                            {showKeys[`${provider.name}_${cred.key}`] ? <FaEyeSlash /> : <FaEye />}
                          </Button>
                        )}
                      </div>
                    </Form.Group>
                  ))}

                  <div className="d-flex gap-2 mt-3">
                    <Button
                      variant="outline-info"
                      size="sm"
                      disabled={saving[provider.name] || !Object.values(providerCreds).some(v => v?.trim())}
                      onClick={() => handleSave(provider)}
                    >
                      {saving[provider.name] ? (
                        <Spinner animation="border" size="sm" />
                      ) : saveSuccess[provider.name] ? (
                        <><FaCheck className="me-1" /> {t('llm.saved', 'Saved')}</>
                      ) : (
                        <><FaSave className="me-1" /> {t('llm.saveKeys', 'Save')}</>
                      )}
                    </Button>

                    {!isActive && provider.configured && (
                      <Button
                        variant="info"
                        size="sm"
                        disabled={activating}
                        onClick={() => handleSetActive(provider.name)}
                      >
                        {activating ? (
                          <Spinner animation="border" size="sm" />
                        ) : (
                          t('llm.setActive', 'Set as Active')
                        )}
                      </Button>
                    )}
                  </div>
                </Card.Body>
              </Card>
            </Col>
          );
        })}
      </Row>
    </Container>
  );
}
