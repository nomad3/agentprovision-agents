import React from "react";
import { Container, Row, Col, Button } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import { FaArrowRight, FaRocket } from "react-icons/fa";

const CTASection = () => {
  const navigate = useNavigate();

  return (
    <section className="cta-section py-5">
      <Container>
        <Row className="align-items-center">
          <Col lg={6} className="text-center text-lg-start mb-4 mb-lg-0">
            <h2 className="display-4 fw-bold text-white mb-3">
              Your AI team is ready to deploy
            </h2>
            <p className="lead text-soft mb-4">
              Create your account and start chatting with Luna in minutes.
              She'll learn your contacts, preferences, and workflows from day one.
            </p>
            <div className="d-flex flex-column flex-md-row gap-3 justify-content-center justify-content-lg-start">
              <Button
                size="lg"
                className="px-5 py-3 cta-primary"
                onClick={() => navigate("/register")}
              >
                <FaRocket className="me-2" />
                Start Free
              </Button>
              <Button
                size="lg"
                variant="outline-light"
                className="px-5 py-3 cta-secondary"
                onClick={() => navigate("/login")}
              >
                Sign In
                <FaArrowRight className="ms-2" />
              </Button>
            </div>
            <div className="trust-badges mt-4">
              <span className="badge-item">Multi-Tenant Isolation</span>
              <span className="badge-item">Encrypted Credential Vault</span>
              <span className="badge-item">Kubernetes Native</span>
            </div>
          </Col>
          <Col lg={6}>
            <div className="cta-visual">
              <div className="cta-stats">
                <div className="stat-item">
                  <div className="stat-number">7</div>
                  <div className="stat-label">Agent Teams</div>
                </div>
                <div className="stat-item">
                  <div className="stat-number">20+</div>
                  <div className="stat-label">Built-in Tools</div>
                </div>
                <div className="stat-item">
                  <div className="stat-number">5</div>
                  <div className="stat-label">Integrations</div>
                </div>
              </div>
            </div>
          </Col>
        </Row>
      </Container>
    </section>
  );
};

export default CTASection;
