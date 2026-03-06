import React from "react";
import { Container, Row, Col } from "react-bootstrap";
import {
  FaRobot,
  FaBrain,
  FaCogs,
  FaPlug,
  FaShieldAlt,
  FaComments,
} from "react-icons/fa";

const FeaturesSection = () => {
  const features = [
    {
      icon: FaRobot,
      title: "Multi-Agent Teams",
      description: "Hierarchical agent orchestration with specialized teams and supervisors",
    },
    {
      icon: FaBrain,
      title: "Persistent Memory",
      description: "Knowledge graph with entity extraction, relations, and contextual recall",
    },
    {
      icon: FaComments,
      title: "AI Chat with Luna",
      description: "Natural language interface that learns your preferences and context",
    },
    {
      icon: FaPlug,
      title: "OAuth Integrations",
      description: "Gmail, Calendar, WhatsApp, GitHub — agents access your real tools",
    },
    {
      icon: FaCogs,
      title: "Durable Workflows",
      description: "Temporal-powered automation with retry logic and audit trails",
    },
    {
      icon: FaShieldAlt,
      title: "Enterprise Security",
      description: "Multi-tenant isolation, encrypted credentials, and JWT auth",
    },
  ];

  return (
    <section className="features-section py-5">
      <Container>
        <Row className="text-center mb-5">
          <Col>
            <h2 className="display-5 fw-bold text-white mb-3">
              Everything you need for production AI agents
            </h2>
            <p className="lead text-soft">
              From orchestration to memory to integrations — built for real-world agentic systems
            </p>
          </Col>
        </Row>

        <Row className="g-4">
          {features.map((feature, index) => (
            <Col md={6} lg={4} key={index} className="mb-4">
              <div className="feature-card text-center">
                <div className="feature-icon">
                  <feature.icon />
                </div>
                <h4 className="feature-title">{feature.title}</h4>
                <p className="feature-description">{feature.description}</p>
              </div>
            </Col>
          ))}
        </Row>
      </Container>
    </section>
  );
};

export default FeaturesSection;
