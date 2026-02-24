import { Button, Col, Container, Row } from "react-bootstrap";
import { FaChartLine } from "react-icons/fa";
import { useTranslation } from "react-i18next";
import NeuralCanvas from "../common/NeuralCanvas";

const noop = () => { };

const HeroSection = ({ onPrimaryCta = noop, onSecondaryCta = noop }) => {
  const { t } = useTranslation(["landing", "common"]);

  return (
    <section className="hero-section pt-5 pb-4" id="hero">
      <NeuralCanvas />
      <div className="hero-overlay" />
      <Container className="hero-content py-5">
        <Row className="align-items-center gy-5">
          <Col lg={6} className="text-center text-lg-start pe-lg-5">
            <span className="badge-glow">{t('hero.badge')}</span>
            <h1 className="display-2 fw-bold mt-4 mb-3 section-heading">
              {t('hero.title')}
            </h1>
            <p className="lead text-soft mt-3 mb-4">
              {t('hero.lead')}
            </p>
            <div className="d-flex flex-column flex-md-row gap-3 justify-content-center justify-content-lg-start mt-4">
              <Button size="lg" className="px-5 py-3" onClick={onPrimaryCta}>
                {t('common:cta.bookDemo', 'Book a Demo')}
              </Button>
              <Button
                size="lg"
                variant="outline-secondary"
                className="px-5 py-3"
                onClick={onSecondaryCta}
              >
                {t('common:cta.watchDemo', 'Watch Demo')}
              </Button>
              <Button
                size="lg"
                variant="outline-light"
                className="px-5 py-3"
                href="https://analytics.servicetsunami.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                <FaChartLine className="me-2" />
                Explore Analytics
              </Button>
            </div>
          </Col>
          <Col lg={6} className="d-none d-lg-block">
            {/* NeuralCanvas fills this space naturally */}
          </Col>
        </Row>
      </Container>
    </section>
  );
};

export default HeroSection;
