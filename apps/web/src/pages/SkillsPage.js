import { useEffect, useState } from 'react';
import { Badge, Card, Col, Container, Row, Spinner } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import Layout from '../components/Layout';
import api from '../services/api';

const SkillsPage = () => {
  const { t } = useTranslation('skills');
  const [skills, setSkills] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetchSkills = async () => {
      try {
        setLoading(true);
        const response = await api.get('/skills/catalog');
        setSkills(response.data || []);
        setError('');
      } catch (err) {
        setError(t('errorLoading'));
      } finally {
        setLoading(false);
      }
    };

    fetchSkills();
  }, [t]);

  return (
    <Layout>
      <Container fluid className="py-4">
        <div className="mb-4">
          <h2 className="fw-bold">{t('title')}</h2>
          <p className="text-muted">{t('subtitle')}</p>
        </div>

        {loading && (
          <div className="text-center py-5">
            <Spinner animation="border" variant="primary" />
          </div>
        )}

        {error && (
          <div className="alert alert-danger">{error}</div>
        )}

        {!loading && !error && skills.length === 0 && (
          <div className="text-center py-5 text-muted">
            <i className="bi bi-puzzle fs-1 d-block mb-3" />
            <p>{t('noSkills')}</p>
          </div>
        )}

        {!loading && !error && skills.length > 0 && (
          <Row xs={1} md={2} lg={3} className="g-4">
            {skills.map((skill) => (
              <Col key={skill.id}>
                <Card className="h-100 shadow-sm">
                  <Card.Body>
                    <div className="d-flex align-items-center justify-content-between mb-2">
                      <Card.Title className="mb-0 fw-semibold">{skill.name}</Card.Title>
                      <Badge bg="secondary" className="text-uppercase">{skill.engine}</Badge>
                    </div>
                    <Card.Text className="text-muted small">{skill.description}</Card.Text>
                    {skill.inputs && skill.inputs.length > 0 && (
                      <div className="mt-3">
                        <p className="small fw-semibold mb-1">{t('inputs')}</p>
                        <ul className="list-unstyled mb-0">
                          {skill.inputs.map((input) => (
                            <li key={input.name} className="small text-muted">
                              <code>{input.name}</code>
                              {' '}
                              <span className="text-secondary">({input.type})</span>
                              {input.required && (
                                <Badge bg="danger" className="ms-1" style={{ fontSize: '0.65em' }}>
                                  {t('required')}
                                </Badge>
                              )}
                              {' — '}
                              {input.description}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </Card.Body>
                  <Card.Footer className="bg-transparent border-top-0 text-muted small">
                    <code>{skill.script_path}</code>
                  </Card.Footer>
                </Card>
              </Col>
            ))}
          </Row>
        )}
      </Container>
    </Layout>
  );
};

export default SkillsPage;
