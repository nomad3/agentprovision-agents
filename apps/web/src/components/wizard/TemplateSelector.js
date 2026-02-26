import React from 'react';
import { Row, Col, Card, Button } from 'react-bootstrap';
import { FaHeadset as Headset, FaChartBar as BarChart, FaBriefcase as Briefcase, FaRobot as Robot, FaEdit as PencilSquare, FaSearch, FaUserTie, FaSitemap, FaBullhorn } from 'react-icons/fa';

const TEMPLATES = [
  {
    id: 'customer_support',
    name: 'Customer Support Agent',
    icon: Headset,
    description: 'Handles customer inquiries, FAQ, order lookups, and general conversation via WhatsApp and chat',
    config: {
      model: 'gpt-4',
      personality: 'friendly',
      temperature: 0.5,
      max_tokens: 1500,
      system_prompt: 'You are a helpful customer support agent. Answer questions from the knowledge base, look up orders and customer records from connected data sources, and handle complaints with empathy. Escalate when you cannot resolve an issue.',
      tools: ['knowledge_search', 'entity_extraction'],
      suggestDatasets: false,
    },
  },
  {
    id: 'data_analyst',
    name: 'Data Analyst Agent',
    icon: BarChart,
    description: 'Analytical and precise. Generates insights from your data using SQL queries',
    config: {
      model: 'gpt-4',
      personality: 'formal',
      temperature: 0.3,
      max_tokens: 2500,
      system_prompt: 'You are a precise data analyst. Use SQL queries to extract insights and present findings with clear numbers and context. Explain technical concepts simply.',
      tools: ['sql_query', 'data_summary'],
      suggestDatasets: true,
    },
  },
  {
    id: 'sales_assistant',
    name: 'Sales Assistant',
    icon: Briefcase,
    description: 'Full sales automation: lead qualification, outreach drafting, pipeline management, and proposal generation',
    config: {
      model: 'gpt-4',
      personality: 'friendly',
      temperature: 0.6,
      max_tokens: 2000,
      system_prompt: 'You are a sales automation specialist. Qualify leads using BANT, draft personalized outreach, manage the sales pipeline, and generate proposals. Always back recommendations with data from the knowledge graph and connected data sources.',
      tools: ['entity_extraction', 'knowledge_search', 'lead_scoring', 'calculator'],
      scoring_rubric: 'ai_lead',
      suggestDatasets: false,
    },
  },
  {
    id: 'general_assistant',
    name: 'General Assistant',
    icon: Robot,
    description: 'Balanced and versatile. Good for general questions and tasks',
    config: {
      model: 'gpt-4',
      personality: 'friendly',
      temperature: 0.7,
      max_tokens: 2000,
      system_prompt: 'You are a helpful AI assistant. Be friendly, clear, and accurate. Assist with a wide range of tasks.',
      tools: ['calculator', 'data_summary'],
      suggestDatasets: false,
    },
  },
  {
    id: 'content_writer',
    name: 'Content Writer',
    icon: PencilSquare,
    description: 'Creative and expressive. Helps draft content, emails, and documents',
    config: {
      model: 'gpt-4',
      personality: 'creative',
      temperature: 0.8,
      max_tokens: 3000,
      system_prompt: 'You are a creative writing assistant. Use imaginative and engaging language. Help draft compelling content.',
      tools: [],
      suggestDatasets: false,
    },
  },
  {
    id: 'research_agent',
    name: 'Research Agent',
    icon: FaSearch,
    description: 'Extract entities from conversations and documents. Build knowledge graphs from unstructured data',
    config: {
      model: 'gpt-4',
      personality: 'formal',
      temperature: 0.3,
      max_tokens: 2500,
      system_prompt: 'You are a meticulous research agent. Extract key entities (people, organizations, concepts) from content. Identify relationships between entities and maintain a structured knowledge graph.',
      tools: ['entity_extraction', 'knowledge_search', 'data_summary', 'lead_scoring'],
      scoring_rubric: 'ai_lead',
      suggestDatasets: false,
    },
  },
  {
    id: 'lead_generation',
    name: 'Lead Generation Agent',
    icon: FaUserTie,
    description: 'Identify prospects, companies, and contacts. Build structured lead databases from conversations',
    config: {
      model: 'gpt-4',
      personality: 'friendly',
      temperature: 0.5,
      max_tokens: 2000,
      system_prompt: 'You are a lead generation specialist. Identify potential prospects, companies, and contacts from conversations. Extract structured information like names, emails, companies, roles, and interests.',
      tools: ['entity_extraction', 'knowledge_search', 'lead_scoring'],
      scoring_rubric: 'ai_lead',
      suggestDatasets: false,
      entity_schema: {
        fields: ['name', 'email', 'company', 'role', 'interest'],
        entity_type: 'prospect',
      },
    },
  },
  {
    id: 'knowledge_manager',
    name: 'Knowledge Manager',
    icon: FaSitemap,
    description: 'Curate, verify, and organize your knowledge graph. Maintain entity accuracy and relationships',
    config: {
      model: 'gpt-4',
      personality: 'formal',
      temperature: 0.4,
      max_tokens: 2500,
      system_prompt: 'You are a knowledge management specialist. Curate and organize the knowledge graph by verifying entities, resolving duplicates, and maintaining accurate relationships between people, organizations, and concepts.',
      tools: ['entity_extraction', 'knowledge_search', 'data_summary'],
      suggestDatasets: false,
    },
  },
  {
    id: 'deal_intelligence',
    name: 'Deal Intelligence Agent',
    icon: Briefcase,
    description: 'Score companies on sell-likelihood for M&A advisory using ownership, market timing, and performance signals',
    config: {
      model: 'gpt-4',
      personality: 'analytical',
      temperature: 0.3,
      max_tokens: 2000,
      system_prompt: 'You are a deal intelligence analyst specializing in M&A advisory. Evaluate companies on sell-likelihood by analyzing ownership structures, market timing signals, and financial performance indicators. Provide structured scoring and reasoning for each assessment.',
      tools: ['entity_extraction', 'knowledge_search', 'lead_scoring'],
      scoring_rubric: 'hca_deal',
      suggestDatasets: false,
    },
  },
  {
    id: 'marketing_intelligence',
    name: 'Marketing Intelligence Agent',
    icon: FaBullhorn,
    description: 'Score leads based on marketing engagement, campaign response, intent signals, and firmographic fit',
    config: {
      model: 'gpt-4',
      personality: 'analytical',
      temperature: 0.3,
      max_tokens: 2000,
      system_prompt: 'You are a marketing intelligence specialist. Score and prioritize leads based on marketing engagement metrics, campaign response patterns, intent signals, and firmographic fit. Provide actionable insights for marketing and sales alignment.',
      tools: ['entity_extraction', 'knowledge_search', 'lead_scoring'],
      scoring_rubric: 'marketing_signal',
      suggestDatasets: false,
    },
  },
];

const TemplateSelector = ({ onSelect, selectedTemplate }) => {
  const handleSelect = (template) => {
    onSelect(template);
  };

  return (
    <div className="template-selector">
      <h3 className="mb-2">What type of agent do you want to create?</h3>
      <p className="text-muted mb-4">Choose a template to get started with pre-configured settings</p>

      <Row className="g-3">
        {TEMPLATES.map((template) => {
          const IconComponent = template.icon;
          const isSelected = selectedTemplate === template.id;

          return (
            <Col key={template.id} md={6} lg={4}>
              <Card
                className={`template-card h-100 ${isSelected ? 'selected' : ''}`}
                style={{ cursor: 'pointer' }}
                onClick={() => handleSelect(template)}
              >
                <Card.Body className="d-flex flex-column align-items-center text-center">
                  <div className="template-icon mb-3">
                    <IconComponent size={48} />
                  </div>
                  <Card.Title className="mb-2">{template.name}</Card.Title>
                  <Card.Text className="text-muted mb-3 flex-grow-1">
                    {template.description}
                  </Card.Text>
                  <Button
                    variant={isSelected ? 'primary' : 'outline-primary'}
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleSelect(template);
                    }}
                  >
                    {isSelected ? 'Selected' : 'Select'}
                  </Button>
                </Card.Body>
              </Card>
            </Col>
          );
        })}
      </Row>

      <div className="mt-4 text-center">
        <small className="text-muted">
          Or <a href="#agent-kits">start from one of your saved agent kits →</a>
        </small>
      </div>
    </div>
  );
};

export { TEMPLATES };
export default TemplateSelector;
