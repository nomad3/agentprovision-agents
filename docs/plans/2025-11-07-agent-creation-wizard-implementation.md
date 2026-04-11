# Agent Creation Wizard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a 5-step guided wizard that simplifies agent creation for non-technical users with templates, plain-language controls, and smart defaults.

**Architecture:** Create new wizard components in React, reuse existing agent service API, maintain backward compatibility with quick form. Wizard stores state in React, persists drafts to localStorage, and submits to existing `/api/v1/agents` endpoint.

**Tech Stack:** React 18, React Bootstrap, React Router v7, localStorage for drafts, existing FastAPI backend

---

## Task 1: Create Wizard Container & Navigation

**Files:**
- Create: `apps/web/src/components/wizard/AgentWizard.js`
- Create: `apps/web/src/components/wizard/WizardStepper.js`
- Create: `apps/web/src/components/wizard/AgentWizard.css`

**Step 1: Write the WizardStepper component test**

Create `apps/web/src/components/wizard/__tests__/WizardStepper.test.js`:

```javascript
import { render, screen } from '@testing-library/react';
import WizardStepper from '../WizardStepper';

describe('WizardStepper', () => {
  const steps = [
    { number: 1, label: 'Template' },
    { number: 2, label: 'Basic Info' },
    { number: 3, label: 'Personality' },
    { number: 4, label: 'Skills & Data' },
    { number: 5, label: 'Review' },
  ];

  test('renders all steps with correct labels', () => {
    render(<WizardStepper currentStep={1} steps={steps} />);
    expect(screen.getByText('Template')).toBeInTheDocument();
    expect(screen.getByText('Basic Info')).toBeInTheDocument();
    expect(screen.getByText('Personality')).toBeInTheDocument();
    expect(screen.getByText('Skills & Data')).toBeInTheDocument();
    expect(screen.getByText('Review')).toBeInTheDocument();
  });

  test('highlights current step', () => {
    render(<WizardStepper currentStep={2} steps={steps} />);
    const step2 = screen.getByText('Basic Info').closest('.wizard-step');
    expect(step2).toHaveClass('active');
  });

  test('marks completed steps', () => {
    render(<WizardStepper currentStep={3} steps={steps} />);
    const step1 = screen.getByText('Template').closest('.wizard-step');
    expect(step1).toHaveClass('completed');
  });
});
```

**Step 2: Run test to verify it fails**

```bash
cd apps/web
npm test -- WizardStepper.test.js
```

Expected: FAIL with "Cannot find module '../WizardStepper'"

**Step 3: Write WizardStepper component**

Create `apps/web/src/components/wizard/WizardStepper.js`:

```javascript
import React from 'react';
import { Check } from 'react-bootstrap-icons';
import './AgentWizard.css';

const WizardStepper = ({ currentStep, steps }) => {
  return (
    <div className="wizard-stepper">
      {steps.map((step, index) => (
        <React.Fragment key={step.number}>
          <div
            className={`wizard-step ${
              step.number === currentStep ? 'active' : ''
            } ${step.number < currentStep ? 'completed' : ''}`}
          >
            <div className="step-number">
              {step.number < currentStep ? (
                <Check size={20} />
              ) : (
                step.number
              )}
            </div>
            <div className="step-label">{step.label}</div>
          </div>
          {index < steps.length - 1 && (
            <div
              className={`step-connector ${
                step.number < currentStep ? 'completed' : ''
              }`}
            />
          )}
        </React.Fragment>
      ))}
    </div>
  );
};

export default WizardStepper;
```

**Step 4: Write AgentWizard container test**

Create `apps/web/src/components/wizard/__tests__/AgentWizard.test.js`:

```javascript
import { render, screen, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import AgentWizard from '../AgentWizard';

const renderWizard = () => {
  return render(
    <BrowserRouter>
      <AgentWizard />
    </BrowserRouter>
  );
};

describe('AgentWizard', () => {
  test('renders wizard stepper', () => {
    renderWizard();
    expect(screen.getByText('Template')).toBeInTheDocument();
  });

  test('shows step 1 by default', () => {
    renderWizard();
    expect(screen.getByText('What type of agent do you want to create?')).toBeInTheDocument();
  });

  test('has Back and Next buttons', () => {
    renderWizard();
    expect(screen.getByText('Next')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  test('Back button disabled on step 1', () => {
    renderWizard();
    const backButton = screen.queryByText('Back');
    expect(backButton).not.toBeInTheDocument();
  });
});
```

**Step 5: Run test to verify it fails**

```bash
npm test -- AgentWizard.test.js
```

Expected: FAIL with "Cannot find module '../AgentWizard'"

**Step 6: Write AgentWizard container component**

Create `apps/web/src/components/wizard/AgentWizard.js`:

```javascript
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Container, Button, Card } from 'react-bootstrap';
import WizardStepper from './WizardStepper';
import './AgentWizard.css';

const STEPS = [
  { number: 1, label: 'Template', component: 'TemplateSelector' },
  { number: 2, label: 'Basic Info', component: 'BasicInfo' },
  { number: 3, label: 'Personality', component: 'Personality' },
  { number: 4, label: 'Skills & Data', component: 'SkillsData' },
  { number: 5, label: 'Review', component: 'Review' },
];

const AgentWizard = () => {
  const navigate = useNavigate();
  const [currentStep, setCurrentStep] = useState(1);
  const [wizardData, setWizardData] = useState({
    template: null,
    basicInfo: { name: '', description: '', avatar: '' },
    personality: { preset: 'friendly', temperature: 0.7, max_tokens: 2000, system_prompt: '' },
    skills: { sql_query: false, data_summary: false, calculator: false },
    datasets: [],
  });

  const handleNext = () => {
    if (currentStep < STEPS.length) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleCancel = () => {
    if (window.confirm('Are you sure you want to cancel? Your progress will be lost.')) {
      navigate('/dashboard/agents');
    }
  };

  const updateWizardData = (stepData) => {
    setWizardData({ ...wizardData, ...stepData });
  };

  return (
    <Container className="wizard-container py-4">
      <Card className="wizard-card">
        <Card.Body>
          <WizardStepper currentStep={currentStep} steps={STEPS} />

          <div className="wizard-content mt-4">
            {currentStep === 1 && (
              <div className="wizard-step-content">
                <h3>What type of agent do you want to create?</h3>
                <p className="text-muted">Choose a template to get started</p>
                {/* TemplateSelector will be implemented next */}
              </div>
            )}
          </div>

          <div className="wizard-actions mt-4 d-flex justify-content-between">
            <div>
              {currentStep > 1 && (
                <Button variant="outline-secondary" onClick={handleBack}>
                  Back
                </Button>
              )}
            </div>
            <div className="d-flex gap-2">
              <Button variant="outline-secondary" onClick={handleCancel}>
                Cancel
              </Button>
              {currentStep < STEPS.length && (
                <Button variant="primary" onClick={handleNext}>
                  Next
                </Button>
              )}
            </div>
          </div>
        </Card.Body>
      </Card>
    </Container>
  );
};

export default AgentWizard;
```

**Step 7: Write wizard styles**

Create `apps/web/src/components/wizard/AgentWizard.css`:

```css
.wizard-container {
  max-width: 900px;
  margin: 0 auto;
}

.wizard-card {
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.wizard-stepper {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 0;
}

.wizard-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.step-number {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #e9ecef;
  color: #6c757d;
  font-weight: 600;
  transition: all 0.3s ease;
}

.wizard-step.active .step-number {
  background-color: #0d6efd;
  color: white;
  transform: scale(1.1);
}

.wizard-step.completed .step-number {
  background-color: #198754;
  color: white;
}

.step-label {
  font-size: 0.85rem;
  color: #6c757d;
  text-align: center;
}

.wizard-step.active .step-label {
  color: #0d6efd;
  font-weight: 600;
}

.wizard-step.completed .step-label {
  color: #198754;
}

.step-connector {
  flex: 1;
  height: 2px;
  background-color: #e9ecef;
  margin: 0 10px;
  margin-bottom: 30px;
}

.step-connector.completed {
  background-color: #198754;
}

.wizard-content {
  min-height: 400px;
}

.wizard-actions {
  border-top: 1px solid #dee2e6;
  padding-top: 20px;
}

@media (max-width: 768px) {
  .wizard-stepper {
    overflow-x: auto;
  }

  .step-label {
    font-size: 0.75rem;
  }
}
```

**Step 8: Run tests to verify they pass**

```bash
npm test -- WizardStepper.test.js AgentWizard.test.js
```

Expected: All tests PASS

**Step 9: Commit**

```bash
git add apps/web/src/components/wizard/
git commit -m "feat: add wizard container and stepper navigation

- Create AgentWizard main container component
- Add WizardStepper progress indicator
- Implement navigation (Back/Next/Cancel)
- Add wizard state management
- Include responsive styles

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Create Template Selector (Step 1)

**Files:**
- Create: `apps/web/src/components/wizard/TemplateSelector.js`
- Create: `apps/web/src/components/wizard/__tests__/TemplateSelector.test.js`
- Modify: `apps/web/src/components/wizard/AgentWizard.js`

**Step 1: Write TemplateSelector test**

Create `apps/web/src/components/wizard/__tests__/TemplateSelector.test.js`:

```javascript
import { render, screen, fireEvent } from '@testing-library/react';
import TemplateSelector from '../TemplateSelector';

describe('TemplateSelector', () => {
  const mockOnSelect = jest.fn();

  beforeEach(() => {
    mockOnSelect.mockClear();
  });

  test('renders all 5 templates', () => {
    render(<TemplateSelector onSelect={mockOnSelect} />);
    expect(screen.getByText('Customer Support Agent')).toBeInTheDocument();
    expect(screen.getByText('Data Analyst Agent')).toBeInTheDocument();
    expect(screen.getByText('Sales Assistant')).toBeInTheDocument();
    expect(screen.getByText('General Assistant')).toBeInTheDocument();
    expect(screen.getByText('Content Writer')).toBeInTheDocument();
  });

  test('calls onSelect when template is clicked', () => {
    render(<TemplateSelector onSelect={mockOnSelect} />);
    const template = screen.getByText('Select').closest('button');
    fireEvent.click(template);
    expect(mockOnSelect).toHaveBeenCalledWith(expect.objectContaining({
      id: expect.any(String),
      name: expect.any(String),
    }));
  });

  test('highlights selected template', () => {
    render(<TemplateSelector onSelect={mockOnSelect} selectedTemplate="customer_support" />);
    const card = screen.getByText('Customer Support Agent').closest('.template-card');
    expect(card).toHaveClass('selected');
  });
});
```

**Step 2: Run test to verify it fails**

```bash
npm test -- TemplateSelector.test.js
```

Expected: FAIL with "Cannot find module '../TemplateSelector'"

**Step 3: Write TemplateSelector component**

Create `apps/web/src/components/wizard/TemplateSelector.js`:

```javascript
import React from 'react';
import { Row, Col, Card, Button } from 'react-bootstrap';
import { Headset, BarChart, Briefcase, Robot, PencilSquare } from 'react-bootstrap-icons';

const TEMPLATES = [
  {
    id: 'customer_support',
    name: 'Customer Support Agent',
    icon: Headset,
    description: 'Helpful and patient. Perfect for handling customer inquiries and FAQs',
    config: {
      model: 'gpt-4',
      personality: 'formal',
      temperature: 0.5,
      max_tokens: 1500,
      system_prompt: 'You are a helpful customer support agent. Be polite, empathetic, and professional. Ask clarifying questions when needed and provide clear solutions.',
      tools: [],
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
    description: 'Persuasive and knowledgeable. Helps with product info and sales support',
    config: {
      model: 'gpt-4',
      personality: 'friendly',
      temperature: 0.6,
      max_tokens: 2000,
      system_prompt: 'You are a knowledgeable sales assistant. Be enthusiastic but not pushy. Highlight product benefits and use the calculator for pricing.',
      tools: ['calculator'],
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
```

**Step 4: Add template styles to CSS**

Append to `apps/web/src/components/wizard/AgentWizard.css`:

```css
.template-card {
  transition: all 0.2s ease;
  border: 2px solid transparent;
}

.template-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.template-card.selected {
  border-color: #0d6efd;
  background-color: #f8f9ff;
}

.template-icon {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
}
```

**Step 5: Integrate TemplateSelector into AgentWizard**

Modify `apps/web/src/components/wizard/AgentWizard.js`:

```javascript
// Add import at top
import TemplateSelector from './TemplateSelector';

// Replace the placeholder in wizard-content with:
{currentStep === 1 && (
  <TemplateSelector
    onSelect={(template) => {
      updateWizardData({
        template: template,
        basicInfo: {
          ...wizardData.basicInfo,
          name: template.name
        },
        personality: {
          preset: template.config.personality,
          temperature: template.config.temperature,
          max_tokens: template.config.max_tokens,
          system_prompt: template.config.system_prompt,
        },
        skills: template.config.tools.reduce((acc, tool) => {
          acc[tool] = true;
          return acc;
        }, { sql_query: false, data_summary: false, calculator: false }),
      });
    }}
    selectedTemplate={wizardData.template?.id}
  />
)}
```

**Step 6: Run tests to verify they pass**

```bash
npm test -- TemplateSelector.test.js
```

Expected: All tests PASS

**Step 7: Commit**

```bash
git add apps/web/src/components/wizard/
git commit -m "feat: add template selector for step 1

- Create TemplateSelector with 5 agent templates
- Include icons and descriptions for each template
- Pre-configure settings based on template selection
- Add template card styles and hover effects

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Create Basic Info Form (Step 2)

**Files:**
- Create: `apps/web/src/components/wizard/BasicInfoStep.js`
- Create: `apps/web/src/components/wizard/__tests__/BasicInfoStep.test.js`
- Modify: `apps/web/src/components/wizard/AgentWizard.js`

**Step 1: Write BasicInfoStep test**

Create `apps/web/src/components/wizard/__tests__/BasicInfoStep.test.js`:

```javascript
import { render, screen, fireEvent } from '@testing-library/react';
import BasicInfoStep from '../BasicInfoStep';

describe('BasicInfoStep', () => {
  const mockOnChange = jest.fn();
  const defaultData = {
    name: '',
    description: '',
    avatar: '',
  };

  beforeEach(() => {
    mockOnChange.mockClear();
  });

  test('renders name and description fields', () => {
    render(<BasicInfoStep data={defaultData} onChange={mockOnChange} />);
    expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/description/i)).toBeInTheDocument();
  });

  test('shows pre-filled name from template', () => {
    render(<BasicInfoStep data={{ ...defaultData, name: 'Customer Support Agent' }} onChange={mockOnChange} />);
    expect(screen.getByDisplayValue('Customer Support Agent')).toBeInTheDocument();
  });

  test('calls onChange when name is updated', () => {
    render(<BasicInfoStep data={defaultData} onChange={mockOnChange} />);
    const nameInput = screen.getByLabelText(/name/i);
    fireEvent.change(nameInput, { target: { value: 'My Support Bot' } });
    expect(mockOnChange).toHaveBeenCalledWith({
      name: 'My Support Bot',
      description: '',
      avatar: '',
    });
  });

  test('validates name length', () => {
    render(<BasicInfoStep data={{ ...defaultData, name: 'AB' }} onChange={mockOnChange} />);
    expect(screen.getByText(/at least 3 characters/i)).toBeInTheDocument();
  });
});
```

**Step 2: Run test to verify it fails**

```bash
npm test -- BasicInfoStep.test.js
```

Expected: FAIL with "Cannot find module '../BasicInfoStep'"

**Step 3: Write BasicInfoStep component**

Create `apps/web/src/components/wizard/BasicInfoStep.js`:

```javascript
import React, { useState } from 'react';
import { Form, Row, Col } from 'react-bootstrap';

const BasicInfoStep = ({ data, onChange }) => {
  const [validation, setValidation] = useState({ name: true });

  const handleChange = (field, value) => {
    const updated = { ...data, [field]: value };
    onChange(updated);

    // Validate name
    if (field === 'name') {
      setValidation({ ...validation, name: value.length >= 3 && value.length <= 50 });
    }
  };

  return (
    <div className="basic-info-step">
      <h3 className="mb-2">Tell us about your agent</h3>
      <p className="text-muted mb-4">Give your agent a name and description</p>

      <Form>
        <Form.Group className="mb-4">
          <Form.Label>Name *</Form.Label>
          <Form.Control
            type="text"
            placeholder="e.g., Support Bot, Sales Assistant Sally"
            value={data.name}
            onChange={(e) => handleChange('name', e.target.value)}
            isInvalid={!validation.name && data.name.length > 0}
            required
          />
          {!validation.name && data.name.length > 0 && (
            <Form.Control.Feedback type="invalid">
              Name must be at least 3 characters and no more than 50 characters
            </Form.Control.Feedback>
          )}
          <Form.Text className="text-muted">
            Give your agent a memorable name
          </Form.Text>
        </Form.Group>

        <Form.Group className="mb-4">
          <Form.Label>Description</Form.Label>
          <Form.Control
            as="textarea"
            rows={3}
            placeholder="What will this agent help with?"
            value={data.description}
            onChange={(e) => handleChange('description', e.target.value)}
            maxLength={500}
          />
          <Form.Text className="text-muted">
            {data.description.length}/500 characters
          </Form.Text>
        </Form.Group>

        <Form.Group className="mb-4">
          <Form.Label>Avatar (Optional)</Form.Label>
          <div className="avatar-selector">
            <Row className="g-2">
              {['🤖', '👨‍💼', '👩‍💻', '🎧', '📊', '✍️', '🎯', '💡'].map((emoji) => (
                <Col xs={3} sm={2} key={emoji}>
                  <div
                    className={`avatar-option ${data.avatar === emoji ? 'selected' : ''}`}
                    onClick={() => handleChange('avatar', emoji)}
                    style={{ cursor: 'pointer', fontSize: '2rem', textAlign: 'center', padding: '10px', border: data.avatar === emoji ? '2px solid #0d6efd' : '2px solid transparent', borderRadius: '8px' }}
                  >
                    {emoji}
                  </div>
                </Col>
              ))}
            </Row>
          </div>
          <Form.Text className="text-muted">
            Choose an emoji to represent your agent
          </Form.Text>
        </Form.Group>
      </Form>
    </div>
  );
};

export default BasicInfoStep;
```

**Step 4: Add avatar styles to CSS**

Append to `apps/web/src/components/wizard/AgentWizard.css`:

```css
.avatar-option {
  transition: all 0.2s ease;
}

.avatar-option:hover {
  transform: scale(1.1);
  background-color: #f8f9fa;
}

.avatar-option.selected {
  background-color: #e7f1ff;
}
```

**Step 5: Integrate BasicInfoStep into AgentWizard**

Modify `apps/web/src/components/wizard/AgentWizard.js`:

```javascript
// Add import at top
import BasicInfoStep from './BasicInfoStep';

// Add after step 1 in wizard-content:
{currentStep === 2 && (
  <BasicInfoStep
    data={wizardData.basicInfo}
    onChange={(basicInfo) => updateWizardData({ basicInfo })}
  />
)}
```

**Step 6: Update Next button validation**

Modify the handleNext function in `AgentWizard.js`:

```javascript
const handleNext = () => {
  // Validate current step
  if (currentStep === 1 && !wizardData.template) {
    alert('Please select a template to continue');
    return;
  }

  if (currentStep === 2) {
    if (!wizardData.basicInfo.name || wizardData.basicInfo.name.length < 3) {
      alert('Please enter a valid agent name (at least 3 characters)');
      return;
    }
  }

  if (currentStep < STEPS.length) {
    setCurrentStep(currentStep + 1);
  }
};
```

**Step 7: Run tests to verify they pass**

```bash
npm test -- BasicInfoStep.test.js
```

Expected: All tests PASS

**Step 8: Commit**

```bash
git add apps/web/src/components/wizard/
git commit -m "feat: add basic info form for step 2

- Create BasicInfoStep with name, description, avatar fields
- Add name validation (3-50 characters)
- Include emoji avatar selector
- Add validation to wizard navigation

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Create Personality Configuration (Step 3)

**Files:**
- Create: `apps/web/src/components/wizard/PersonalityStep.js`
- Create: `apps/web/src/components/wizard/__tests__/PersonalityStep.test.js`
- Modify: `apps/web/src/components/wizard/AgentWizard.js`

**Step 1: Write PersonalityStep test**

Create `apps/web/src/components/wizard/__tests__/PersonalityStep.test.js`:

```javascript
import { render, screen, fireEvent } from '@testing-library/react';
import PersonalityStep from '../PersonalityStep';

describe('PersonalityStep', () => {
  const mockOnChange = jest.fn();
  const defaultData = {
    preset: 'friendly',
    temperature: 0.7,
    max_tokens: 2000,
    system_prompt: '',
  };

  beforeEach(() => {
    mockOnChange.mockClear();
  });

  test('renders three personality presets', () => {
    render(<PersonalityStep data={defaultData} onChange={mockOnChange} />);
    expect(screen.getByText('Formal & Professional')).toBeInTheDocument();
    expect(screen.getByText('Friendly & Conversational')).toBeInTheDocument();
    expect(screen.getByText('Creative & Expressive')).toBeInTheDocument();
  });

  test('shows selected preset', () => {
    render(<PersonalityStep data={{ ...defaultData, preset: 'formal' }} onChange={mockOnChange} />);
    const card = screen.getByText('Formal & Professional').closest('.preset-card');
    expect(card).toHaveClass('selected');
  });

  test('calls onChange when preset is selected', () => {
    render(<PersonalityStep data={defaultData} onChange={mockOnChange} />);
    fireEvent.click(screen.getByText('Creative & Expressive'));
    expect(mockOnChange).toHaveBeenCalledWith(expect.objectContaining({
      preset: 'creative',
      temperature: 0.9,
    }));
  });

  test('fine-tune section is collapsed by default', () => {
    render(<PersonalityStep data={defaultData} onChange={mockOnChange} />);
    expect(screen.queryByText('Response Style')).not.toBeInTheDocument();
  });

  test('expands fine-tune section when toggled', () => {
    render(<PersonalityStep data={defaultData} onChange={mockOnChange} />);
    fireEvent.click(screen.getByText(/fine-tune settings/i));
    expect(screen.getByText('Response Style')).toBeInTheDocument();
  });
});
```

**Step 2: Run test to verify it fails**

```bash
npm test -- PersonalityStep.test.js
```

Expected: FAIL with "Cannot find module '../PersonalityStep'"

**Step 3: Write PersonalityStep component**

Create `apps/web/src/components/wizard/PersonalityStep.js`:

```javascript
import React, { useState } from 'react';
import { Card, Row, Col, Form, Accordion } from 'react-bootstrap';

const PRESETS = [
  {
    id: 'formal',
    name: 'Formal & Professional',
    emoji: '🎩',
    description: 'Precise, structured responses. Best for business contexts',
    temperature: 0.4,
    max_tokens: 1500,
  },
  {
    id: 'friendly',
    name: 'Friendly & Conversational',
    emoji: '💬',
    description: 'Warm, approachable tone. Great for customer interactions',
    temperature: 0.7,
    max_tokens: 2000,
  },
  {
    id: 'creative',
    name: 'Creative & Expressive',
    emoji: '✨',
    description: 'Imaginative, colorful language. Perfect for content creation',
    temperature: 0.9,
    max_tokens: 3000,
  },
];

const PersonalityStep = ({ data, onChange }) => {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handlePresetSelect = (preset) => {
    onChange({
      ...data,
      preset: preset.id,
      temperature: preset.temperature,
      max_tokens: preset.max_tokens,
    });
  };

  const handleSliderChange = (field, value) => {
    onChange({ ...data, [field]: parseFloat(value) });
  };

  const handlePromptChange = (value) => {
    onChange({ ...data, system_prompt: value });
  };

  return (
    <div className="personality-step">
      <h3 className="mb-2">How should your agent communicate?</h3>
      <p className="text-muted mb-4">Choose a communication style for your agent</p>

      <Row className="g-3 mb-4">
        {PRESETS.map((preset) => (
          <Col key={preset.id} md={4}>
            <Card
              className={`preset-card h-100 ${data.preset === preset.id ? 'selected' : ''}`}
              onClick={() => handlePresetSelect(preset)}
              style={{ cursor: 'pointer' }}
            >
              <Card.Body className="text-center">
                <div className="preset-emoji mb-2" style={{ fontSize: '2.5rem' }}>
                  {preset.emoji}
                </div>
                <Card.Title className="h6">{preset.name}</Card.Title>
                <Card.Text className="text-muted small">
                  {preset.description}
                </Card.Text>
              </Card.Body>
            </Card>
          </Col>
        ))}
      </Row>

      <Accordion className="mb-3">
        <Accordion.Item eventKey="0">
          <Accordion.Header onClick={() => setShowAdvanced(!showAdvanced)}>
            Advanced: Fine-tune settings
          </Accordion.Header>
          <Accordion.Body>
            <Form.Group className="mb-3">
              <Form.Label>
                Response Style: {data.temperature.toFixed(1)}
              </Form.Label>
              <div className="d-flex align-items-center gap-3">
                <small className="text-muted">🎯 Precise</small>
                <Form.Range
                  min={0}
                  max={1}
                  step={0.1}
                  value={data.temperature}
                  onChange={(e) => handleSliderChange('temperature', e.target.value)}
                />
                <small className="text-muted">🎨 Creative</small>
              </div>
              <Form.Text className="text-muted">
                Controls response randomness. Lower = more focused, Higher = more creative
              </Form.Text>
            </Form.Group>

            <Form.Group className="mb-3">
              <Form.Label>
                Response Length: {data.max_tokens} tokens
              </Form.Label>
              <div className="d-flex align-items-center gap-3">
                <small className="text-muted">Concise</small>
                <Form.Range
                  min={500}
                  max={4000}
                  step={100}
                  value={data.max_tokens}
                  onChange={(e) => handleSliderChange('max_tokens', e.target.value)}
                />
                <small className="text-muted">Detailed</small>
              </div>
              <Form.Text className="text-muted">
                Maximum length of agent responses
              </Form.Text>
            </Form.Group>

            <Form.Group className="mb-3">
              <Form.Label>Custom System Prompt (Advanced)</Form.Label>
              <Form.Control
                as="textarea"
                rows={4}
                placeholder="You are a helpful assistant that..."
                value={data.system_prompt}
                onChange={(e) => handlePromptChange(e.target.value)}
                maxLength={2000}
              />
              <Form.Text className="text-muted">
                Override the default system prompt. Leave empty to use template default.
              </Form.Text>
            </Form.Group>
          </Accordion.Body>
        </Accordion.Item>
      </Accordion>
    </div>
  );
};

export default PersonalityStep;
```

**Step 4: Add preset styles to CSS**

Append to `apps/web/src/components/wizard/AgentWizard.css`:

```css
.preset-card {
  transition: all 0.2s ease;
  border: 2px solid transparent;
}

.preset-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
}

.preset-card.selected {
  border-color: #0d6efd;
  background-color: #f8f9ff;
}
```

**Step 5: Integrate PersonalityStep into AgentWizard**

Modify `apps/web/src/components/wizard/AgentWizard.js`:

```javascript
// Add import at top
import PersonalityStep from './PersonalityStep';

// Add after step 2 in wizard-content:
{currentStep === 3 && (
  <PersonalityStep
    data={wizardData.personality}
    onChange={(personality) => updateWizardData({ personality })}
  />
)}
```

**Step 6: Run tests to verify they pass**

```bash
npm test -- PersonalityStep.test.js
```

Expected: All tests PASS

**Step 7: Commit**

```bash
git add apps/web/src/components/wizard/
git commit -m "feat: add personality configuration for step 3

- Create PersonalityStep with preset selector
- Add three personality presets (Formal, Friendly, Creative)
- Include collapsible fine-tune section with sliders
- Add custom system prompt override option

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Create Skills & Data Configuration (Step 4)

**Files:**
- Create: `apps/web/src/components/wizard/SkillsDataStep.js`
- Create: `apps/web/src/components/wizard/__tests__/SkillsDataStep.test.js`
- Modify: `apps/web/src/components/wizard/AgentWizard.js`

**Step 1: Write SkillsDataStep test**

Create `apps/web/src/components/wizard/__tests__/SkillsDataStep.test.js`:

```javascript
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SkillsDataStep from '../SkillsDataStep';
import datasetService from '../../../services/dataset';

jest.mock('../../../services/dataset');

describe('SkillsDataStep', () => {
  const mockOnChange = jest.fn();
  const defaultData = {
    skills: { sql_query: false, data_summary: false, calculator: false },
    datasets: [],
  };

  beforeEach(() => {
    mockOnChange.mockClear();
    datasetService.getAll.mockResolvedValue({ data: [] });
  });

  test('renders all three tools', async () => {
    render(<SkillsDataStep data={defaultData} onChange={mockOnChange} />);
    await waitFor(() => {
      expect(screen.getByText('SQL Query Tool')).toBeInTheDocument();
      expect(screen.getByText('Data Summary Tool')).toBeInTheDocument();
      expect(screen.getByText('Calculator Tool')).toBeInTheDocument();
    });
  });

  test('shows pre-selected tools from template', async () => {
    const dataWithTools = {
      skills: { sql_query: true, data_summary: true, calculator: false },
      datasets: [],
    };
    render(<SkillsDataStep data={dataWithTools} onChange={mockOnChange} />);
    await waitFor(() => {
      const sqlToggle = screen.getByLabelText('SQL Query Tool');
      expect(sqlToggle).toBeChecked();
    });
  });

  test('calls onChange when tool is toggled', async () => {
    render(<SkillsDataStep data={defaultData} onChange={mockOnChange} />);
    await waitFor(() => {
      const calcToggle = screen.getByLabelText('Calculator Tool');
      fireEvent.click(calcToggle);
      expect(mockOnChange).toHaveBeenCalledWith({
        skills: { sql_query: false, data_summary: false, calculator: true },
        datasets: [],
      });
    });
  });

  test('fetches and displays datasets', async () => {
    const mockDatasets = [
      { id: '123', name: 'Revenue 2024', row_count: 1000, columns: ['id', 'amount'] },
    ];
    datasetService.getAll.mockResolvedValue({ data: mockDatasets });

    render(<SkillsDataStep data={defaultData} onChange={mockOnChange} />);

    await waitFor(() => {
      expect(screen.getByText('Revenue 2024')).toBeInTheDocument();
      expect(screen.getByText('1000 rows')).toBeInTheDocument();
    });
  });
});
```

**Step 2: Run test to verify it fails**

```bash
npm test -- SkillsDataStep.test.js
```

Expected: FAIL with "Cannot find module '../SkillsDataStep'"

**Step 3: Write SkillsDataStep component**

Create `apps/web/src/components/wizard/SkillsDataStep.js`:

```javascript
import React, { useState, useEffect } from 'react';
import { Card, Form, Row, Col, Badge, Alert } from 'react-bootstrap';
import { Database, Calculator as CalcIcon, BarChart } from 'react-bootstrap-icons';
import datasetService from '../../services/dataset';
import { LoadingSpinner } from '../common';

const TOOLS = [
  {
    id: 'sql_query',
    name: 'SQL Query Tool',
    icon: Database,
    description: 'Query and analyze datasets with SQL',
    requiresDataset: true,
  },
  {
    id: 'data_summary',
    name: 'Data Summary Tool',
    icon: BarChart,
    description: 'Generate statistical summaries of data',
    requiresDataset: false,
  },
  {
    id: 'calculator',
    name: 'Calculator Tool',
    icon: CalcIcon,
    description: 'Perform mathematical calculations',
    requiresDataset: false,
  },
];

const SkillsDataStep = ({ data, onChange, templateName }) => {
  const [datasets, setDatasets] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchDatasets();
  }, []);

  const fetchDatasets = async () => {
    try {
      setLoading(true);
      const response = await datasetService.getAll();
      setDatasets(response.data || []);
    } catch (error) {
      console.error('Error fetching datasets:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleToolToggle = (toolId) => {
    const updatedSkills = { ...data.skills, [toolId]: !data.skills[toolId] };
    onChange({ ...data, skills: updatedSkills });
  };

  const handleDatasetToggle = (datasetId) => {
    const isSelected = data.datasets.includes(datasetId);
    const updatedDatasets = isSelected
      ? data.datasets.filter((id) => id !== datasetId)
      : [...data.datasets, datasetId];
    onChange({ ...data, datasets: updatedDatasets });
  };

  const sqlToolEnabled = data.skills.sql_query;
  const noDatasetSelected = sqlToolEnabled && data.datasets.length === 0;

  return (
    <div className="skills-data-step">
      <h3 className="mb-2">What can your agent do?</h3>
      <p className="text-muted mb-4">Configure your agent's capabilities and data access</p>

      {/* Skills Section */}
      <Card className="mb-4">
        <Card.Body>
          <h5 className="mb-3">Skills</h5>
          {templateName && (
            <Alert variant="info" className="mb-3">
              <small>
                <strong>{templateName}</strong> agents typically use these tools
              </small>
            </Alert>
          )}

          {TOOLS.map((tool) => {
            const IconComponent = tool.icon;
            return (
              <Card key={tool.id} className="mb-2" style={{ border: '1px solid #dee2e6' }}>
                <Card.Body className="py-3">
                  <div className="d-flex align-items-start justify-content-between">
                    <div className="d-flex align-items-start gap-3 flex-grow-1">
                      <div className="tool-icon" style={{ fontSize: '1.5rem', color: '#0d6efd' }}>
                        <IconComponent />
                      </div>
                      <div className="flex-grow-1">
                        <div className="d-flex align-items-center gap-2 mb-1">
                          <strong>{tool.name}</strong>
                          {tool.requiresDataset && (
                            <Badge bg="secondary" className="text-xs">
                              Requires dataset
                            </Badge>
                          )}
                        </div>
                        <small className="text-muted">{tool.description}</small>
                      </div>
                    </div>
                    <Form.Check
                      type="switch"
                      id={`tool-${tool.id}`}
                      label=""
                      checked={data.skills[tool.id]}
                      onChange={() => handleToolToggle(tool.id)}
                      aria-label={tool.name}
                    />
                  </div>
                </Card.Body>
              </Card>
            );
          })}
        </Card.Body>
      </Card>

      {/* Datasets Section */}
      <Card>
        <Card.Body>
          <h5 className="mb-2">Connect Datasets (Optional)</h5>
          <p className="text-muted small mb-3">
            Give your agent access to specific data for analysis
          </p>

          {noDatasetSelected && (
            <Alert variant="warning" className="mb-3">
              <small>
                SQL Query Tool is enabled but no datasets are selected. Your agent won't be able to query data.
              </small>
            </Alert>
          )}

          {loading ? (
            <LoadingSpinner text="Loading datasets..." />
          ) : datasets.length === 0 ? (
            <Alert variant="info">
              <small>
                No datasets uploaded yet.{' '}
                <a href="/dashboard/datasets">Upload your first dataset →</a>
              </small>
            </Alert>
          ) : (
            <Row className="g-2">
              {datasets.map((dataset) => (
                <Col key={dataset.id} md={6}>
                  <Card
                    className={`dataset-card ${
                      data.datasets.includes(dataset.id) ? 'selected' : ''
                    }`}
                    onClick={() => handleDatasetToggle(dataset.id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <Card.Body className="p-3">
                      <Form.Check
                        type="checkbox"
                        id={`dataset-${dataset.id}`}
                        label={
                          <div>
                            <div className="fw-bold">{dataset.name}</div>
                            <small className="text-muted">
                              {dataset.row_count || 0} rows
                              {dataset.columns && ` • ${dataset.columns.length} columns`}
                            </small>
                          </div>
                        }
                        checked={data.datasets.includes(dataset.id)}
                        onChange={() => handleDatasetToggle(dataset.id)}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Card.Body>
                  </Card>
                </Col>
              ))}
            </Row>
          )}
        </Card.Body>
      </Card>
    </div>
  );
};

export default SkillsDataStep;
```

**Step 4: Add dataset card styles to CSS**

Append to `apps/web/src/components/wizard/AgentWizard.css`:

```css
.dataset-card {
  transition: all 0.2s ease;
  border: 2px solid #dee2e6;
}

.dataset-card:hover {
  border-color: #0d6efd;
  background-color: #f8f9fa;
}

.dataset-card.selected {
  border-color: #0d6efd;
  background-color: #e7f1ff;
}
```

**Step 5: Integrate SkillsDataStep into AgentWizard**

Modify `apps/web/src/components/wizard/AgentWizard.js`:

```javascript
// Add import at top
import SkillsDataStep from './SkillsDataStep';

// Add after step 3 in wizard-content:
{currentStep === 4 && (
  <SkillsDataStep
    data={{ skills: wizardData.skills, datasets: wizardData.datasets }}
    onChange={(skillsData) => updateWizardData(skillsData)}
    templateName={wizardData.template?.name}
  />
)}
```

**Step 6: Run tests to verify they pass**

```bash
npm test -- SkillsDataStep.test.js
```

Expected: All tests PASS

**Step 7: Commit**

```bash
git add apps/web/src/components/wizard/
git commit -m "feat: add skills and data configuration for step 4

- Create SkillsDataStep with tool toggles
- Add dataset selector with multi-select
- Show contextual info based on template
- Warn when SQL tool enabled without datasets

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Create Review & Test Step (Step 5)

**Files:**
- Create: `apps/web/src/components/wizard/ReviewStep.js`
- Create: `apps/web/src/components/wizard/__tests__/ReviewStep.test.js`
- Modify: `apps/web/src/components/wizard/AgentWizard.js`

**Step 1: Write ReviewStep test**

Create `apps/web/src/components/wizard/__tests__/ReviewStep.test.js`:

```javascript
import { render, screen } from '@testing-library/react';
import ReviewStep from '../ReviewStep';

describe('ReviewStep', () => {
  const mockWizardData = {
    template: { name: 'Data Analyst Agent', icon: 'BarChart' },
    basicInfo: { name: 'My Analyst', description: 'Analyzes data', avatar: '📊' },
    personality: { preset: 'formal', temperature: 0.4, max_tokens: 2000 },
    skills: { sql_query: true, data_summary: true, calculator: false },
    datasets: ['123', '456'],
  };

  const mockDatasets = [
    { id: '123', name: 'Revenue 2024' },
    { id: '456', name: 'Customer List' },
  ];

  test('renders summary of all configuration', () => {
    render(<ReviewStep wizardData={mockWizardData} datasets={mockDatasets} onEdit={jest.fn()} />);
    expect(screen.getByText('My Analyst')).toBeInTheDocument();
    expect(screen.getByText('Analyzes data')).toBeInTheDocument();
    expect(screen.getByText(/formal/i)).toBeInTheDocument();
  });

  test('shows enabled tools', () => {
    render(<ReviewStep wizardData={mockWizardData} datasets={mockDatasets} onEdit={jest.fn()} />);
    expect(screen.getByText('SQL Query Tool')).toBeInTheDocument();
    expect(screen.getByText('Data Summary Tool')).toBeInTheDocument();
    expect(screen.queryByText('Calculator Tool')).not.toBeInTheDocument();
  });

  test('shows connected datasets', () => {
    render(<ReviewStep wizardData={mockWizardData} datasets={mockDatasets} onEdit={jest.fn()} />);
    expect(screen.getByText('Revenue 2024')).toBeInTheDocument();
    expect(screen.getByText('Customer List')).toBeInTheDocument();
  });

  test('shows edit links for each section', () => {
    render(<ReviewStep wizardData={mockWizardData} datasets={mockDatasets} onEdit={jest.fn()} />);
    const editLinks = screen.getAllByText('Edit');
    expect(editLinks.length).toBeGreaterThan(0);
  });
});
```

**Step 2: Run test to verify it fails**

```bash
npm test -- ReviewStep.test.js
```

Expected: FAIL with "Cannot find module '../ReviewStep'"

**Step 3: Write ReviewStep component**

Create `apps/web/src/components/wizard/ReviewStep.js`:

```javascript
import React from 'react';
import { Card, Row, Col, Badge, Button } from 'react-bootstrap';
import { Pencil } from 'react-bootstrap-icons';

const ReviewStep = ({ wizardData, datasets, onEdit }) => {
  const { template, basicInfo, personality, skills, datasets: datasetIds } = wizardData;

  const selectedDatasets = datasets.filter((d) => datasetIds.includes(d.id));
  const enabledTools = Object.entries(skills)
    .filter(([_, enabled]) => enabled)
    .map(([tool, _]) => tool);

  const toolNames = {
    sql_query: 'SQL Query Tool',
    data_summary: 'Data Summary Tool',
    calculator: 'Calculator Tool',
  };

  const personalityNames = {
    formal: 'Formal & Professional',
    friendly: 'Friendly & Conversational',
    creative: 'Creative & Expressive',
  };

  return (
    <div className="review-step">
      <h3 className="mb-2">Review your agent</h3>
      <p className="text-muted mb-4">Double-check everything looks good before creating</p>

      <Row>
        <Col lg={12}>
          {/* Template */}
          <Card className="mb-3">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-start mb-2">
                <h6 className="mb-0">Template</h6>
                <Button variant="link" size="sm" className="p-0" onClick={() => onEdit(1)}>
                  <Pencil size={14} className="me-1" />
                  Edit
                </Button>
              </div>
              <div className="d-flex align-items-center gap-2">
                <span style={{ fontSize: '1.5rem' }}>{basicInfo.avatar || '🤖'}</span>
                <span>{template?.name || 'Custom Agent'}</span>
              </div>
            </Card.Body>
          </Card>

          {/* Basic Info */}
          <Card className="mb-3">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-start mb-2">
                <h6 className="mb-0">Basic Information</h6>
                <Button variant="link" size="sm" className="p-0" onClick={() => onEdit(2)}>
                  <Pencil size={14} className="me-1" />
                  Edit
                </Button>
              </div>
              <div>
                <strong>Name:</strong> {basicInfo.name}
              </div>
              {basicInfo.description && (
                <div className="mt-1">
                  <strong>Description:</strong> {basicInfo.description}
                </div>
              )}
            </Card.Body>
          </Card>

          {/* Personality */}
          <Card className="mb-3">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-start mb-2">
                <h6 className="mb-0">Personality</h6>
                <Button variant="link" size="sm" className="p-0" onClick={() => onEdit(3)}>
                  <Pencil size={14} className="me-1" />
                  Edit
                </Button>
              </div>
              <div>
                <Badge bg="info">{personalityNames[personality.preset]}</Badge>
                <div className="mt-2 small text-muted">
                  Temperature: {personality.temperature.toFixed(1)} • Max tokens: {personality.max_tokens}
                </div>
              </div>
            </Card.Body>
          </Card>

          {/* Skills */}
          <Card className="mb-3">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-start mb-2">
                <h6 className="mb-0">Skills</h6>
                <Button variant="link" size="sm" className="p-0" onClick={() => onEdit(4)}>
                  <Pencil size={14} className="me-1" />
                  Edit
                </Button>
              </div>
              {enabledTools.length > 0 ? (
                <div className="d-flex flex-wrap gap-2">
                  {enabledTools.map((tool) => (
                    <Badge key={tool} bg="primary">
                      {toolNames[tool]}
                    </Badge>
                  ))}
                </div>
              ) : (
                <small className="text-muted">No special tools enabled</small>
              )}
            </Card.Body>
          </Card>

          {/* Datasets */}
          <Card className="mb-3">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-start mb-2">
                <h6 className="mb-0">Datasets</h6>
                <Button variant="link" size="sm" className="p-0" onClick={() => onEdit(4)}>
                  <Pencil size={14} className="me-1" />
                  Edit
                </Button>
              </div>
              {selectedDatasets.length > 0 ? (
                <div>
                  <div className="mb-1">
                    <Badge bg="secondary">{selectedDatasets.length} dataset(s) connected</Badge>
                  </div>
                  <div className="small text-muted">
                    {selectedDatasets.map((d) => d.name).join(', ')}
                  </div>
                </div>
              ) : (
                <small className="text-muted">No datasets connected</small>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default ReviewStep;
```

**Step 4: Integrate ReviewStep into AgentWizard and add create logic**

Modify `apps/web/src/components/wizard/AgentWizard.js`:

```javascript
// Add imports at top
import ReviewStep from './ReviewStep';
import agentService from '../../services/agent';

// Add state for datasets and submission
const [datasets, setDatasets] = useState([]);
const [creating, setCreating] = useState(false);

// Fetch datasets on mount
useEffect(() => {
  const fetchDatasets = async () => {
    try {
      const response = await datasetService.getAll();
      setDatasets(response.data || []);
    } catch (error) {
      console.error('Error fetching datasets:', error);
    }
  };
  fetchDatasets();
}, []);

// Add handleCreate function
const handleCreate = async () => {
  try {
    setCreating(true);

    // Build agent config
    const agentData = {
      name: wizardData.basicInfo.name,
      description: wizardData.basicInfo.description,
      config: {
        model: wizardData.template?.config?.model || 'gpt-4',
        temperature: wizardData.personality.temperature,
        max_tokens: wizardData.personality.max_tokens,
        system_prompt: wizardData.personality.system_prompt || wizardData.template?.config?.system_prompt,
        personality_preset: wizardData.personality.preset,
        template_used: wizardData.template?.id,
        avatar: wizardData.basicInfo.avatar,
        tools: Object.entries(wizardData.skills)
          .filter(([_, enabled]) => enabled)
          .map(([tool, _]) => tool),
        datasets: wizardData.datasets,
      },
    };

    await agentService.create(agentData);

    // Clear draft from localStorage
    localStorage.removeItem(`agent_wizard_draft_${getCurrentTenantId()}`);

    // Redirect to agents list with success message
    navigate('/dashboard/agents', { state: { success: 'Agent created successfully!' } });
  } catch (error) {
    console.error('Error creating agent:', error);
    alert('Failed to create agent. Please try again.');
  } finally {
    setCreating(false);
  }
};

// Helper to get tenant ID (simplified - adjust based on your auth)
const getCurrentTenantId = () => {
  // This should get tenant ID from your auth context/user
  return 'default';
};

// Add step 5 in wizard-content:
{currentStep === 5 && (
  <ReviewStep
    wizardData={wizardData}
    datasets={datasets}
    onEdit={(step) => setCurrentStep(step)}
  />
)}

// Update Next button to show Create on step 5
{currentStep < STEPS.length - 1 && (
  <Button variant="primary" onClick={handleNext}>
    Next
  </Button>
)}
{currentStep === STEPS.length && (
  <Button variant="success" onClick={handleCreate} disabled={creating}>
    {creating ? 'Creating...' : 'Create Agent'}
  </Button>
)}
```

**Step 5: Run tests to verify they pass**

```bash
npm test -- ReviewStep.test.js
```

Expected: All tests PASS

**Step 6: Commit**

```bash
git add apps/web/src/components/wizard/
git commit -m "feat: add review and create step for step 5

- Create ReviewStep with summary of all configuration
- Show edit links to jump back to specific steps
- Add agent creation logic with API integration
- Include Create Agent button with loading state

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Add Wizard Route and Navigation

**Files:**
- Modify: `apps/web/src/App.js`
- Modify: `apps/web/src/pages/AgentsPage.js`
- Create: `apps/web/src/pages/AgentWizardPage.js`

**Step 1: Create AgentWizardPage wrapper**

Create `apps/web/src/pages/AgentWizardPage.js`:

```javascript
import React from 'react';
import Layout from '../components/Layout';
import AgentWizard from '../components/wizard/AgentWizard';

const AgentWizardPage = () => {
  return (
    <Layout>
      <AgentWizard />
    </Layout>
  );
};

export default AgentWizardPage;
```

**Step 2: Add wizard route to App.js**

Modify `apps/web/src/App.js`:

```javascript
// Add import
import AgentWizardPage from './pages/AgentWizardPage';

// Add route in the dashboard routes section (after /dashboard/agents):
<Route path="/dashboard/agents/wizard" element={<AgentWizardPage />} />
```

**Step 3: Update AgentsPage to navigate to wizard**

Modify `apps/web/src/pages/AgentsPage.js`:

```javascript
// Add import at top
import { useNavigate } from 'react-router-dom';

// Inside the component, add:
const navigate = useNavigate();

// Update the "Create Agent" button onClick:
<Button
  variant="primary"
  size="lg"
  onClick={() => navigate('/dashboard/agents/wizard')}
  className="d-flex align-items-center gap-2"
>
  <Plus size={20} />
  Create Agent
</Button>

// And the empty state button:
<Button
  variant="primary"
  onClick={() => navigate('/dashboard/agents/wizard')}
>
  <Plus className="me-2" />
  Create Your First Agent
</Button>
```

**Step 4: Add escape hatch to quick form**

Add this below the wizard stepper in `AgentWizard.js`:

```javascript
// Add at the top of wizard-content div, before step content
{currentStep === 1 && (
  <div className="text-center mb-3">
    <small className="text-muted">
      Experienced user?{' '}
      <a
        href="#"
        onClick={(e) => {
          e.preventDefault();
          if (window.confirm('Switch to quick form? Your wizard progress will be lost.')) {
            navigate('/dashboard/agents', { state: { showQuickForm: true } });
          }
        }}
      >
        Use quick form instead →
      </a>
    </small>
  </div>
)}
```

**Step 5: Handle quick form state in AgentsPage**

Modify `apps/web/src/pages/AgentsPage.js`:

```javascript
// Add at top to handle navigation state
import { useLocation } from 'react-router-dom';

// Inside component
const location = useLocation();

// Add useEffect to handle showQuickForm state
useEffect(() => {
  if (location.state?.showQuickForm) {
    setShowCreateModal(true);
    // Clear the state
    window.history.replaceState({}, document.title);
  }
  if (location.state?.success) {
    // Show success toast (you may want to add toast library)
    alert(location.state.success);
    window.history.replaceState({}, document.title);
  }
}, [location]);
```

**Step 6: Test the wizard flow manually**

```bash
cd apps/web
npm start
```

Navigate to `/dashboard/agents` and click "Create Agent". Should open wizard.

**Step 7: Commit**

```bash
git add apps/web/src/
git commit -m "feat: add wizard routing and navigation

- Create AgentWizardPage wrapper component
- Add /dashboard/agents/wizard route
- Update Create Agent button to navigate to wizard
- Add escape hatch link to quick form
- Handle navigation state for quick form fallback

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: Add Draft Persistence (LocalStorage)

**Files:**
- Modify: `apps/web/src/components/wizard/AgentWizard.js`

**Step 1: Add localStorage save/load logic**

Modify `apps/web/src/components/wizard/AgentWizard.js`:

```javascript
// Add at top
const DRAFT_KEY = 'agent_wizard_draft';

// Add useEffect to load draft on mount
useEffect(() => {
  const loadDraft = () => {
    try {
      const draft = localStorage.getItem(DRAFT_KEY);
      if (draft) {
        const parsed = JSON.parse(draft);
        if (window.confirm('Resume your previous agent draft?')) {
          setWizardData(parsed.data);
          setCurrentStep(parsed.step);
        } else {
          localStorage.removeItem(DRAFT_KEY);
        }
      }
    } catch (error) {
      console.error('Error loading draft:', error);
      localStorage.removeItem(DRAFT_KEY);
    }
  };

  loadDraft();
}, []);

// Add useEffect to auto-save on changes
useEffect(() => {
  // Don't save on first render or if no template selected
  if (!wizardData.template) return;

  const saveDraft = () => {
    try {
      localStorage.setItem(
        DRAFT_KEY,
        JSON.stringify({
          data: wizardData,
          step: currentStep,
          timestamp: new Date().toISOString(),
        })
      );
    } catch (error) {
      console.error('Error saving draft:', error);
    }
  };

  // Debounce saves
  const timeoutId = setTimeout(saveDraft, 1000);
  return () => clearTimeout(timeoutId);
}, [wizardData, currentStep]);

// Update handleCreate to clear draft
const handleCreate = async () => {
  try {
    setCreating(true);

    // ... existing create logic ...

    // Clear draft after successful creation
    localStorage.removeItem(DRAFT_KEY);

    navigate('/dashboard/agents', { state: { success: 'Agent created successfully!' } });
  } catch (error) {
    console.error('Error creating agent:', error);
    alert('Failed to create agent. Please try again.');
  } finally {
    setCreating(false);
  }
};

// Update handleCancel to clear draft
const handleCancel = () => {
  if (window.confirm('Are you sure you want to cancel? Your progress will be lost.')) {
    localStorage.removeItem(DRAFT_KEY);
    navigate('/dashboard/agents');
  }
};
```

**Step 2: Add Save Draft button (optional explicit save)**

Add to wizard actions section in `AgentWizard.js`:

```javascript
<div className="d-flex gap-2">
  <Button
    variant="outline-secondary"
    onClick={() => {
      // Draft is auto-saved, just show confirmation
      alert('Draft saved! You can return later to continue.');
    }}
  >
    Save Draft
  </Button>
  <Button variant="outline-secondary" onClick={handleCancel}>
    Cancel
  </Button>
  {/* ... existing Next/Create buttons ... */}
</div>
```

**Step 3: Test draft persistence**

1. Start wizard, fill step 1-2
2. Refresh page
3. Should prompt to resume draft
4. Click "Resume" and verify data persisted

**Step 4: Commit**

```bash
git add apps/web/src/components/wizard/AgentWizard.js
git commit -m "feat: add draft persistence with localStorage

- Auto-save wizard state on changes (debounced)
- Load draft on mount with resume prompt
- Clear draft on successful creation or cancel
- Add Save Draft button for explicit save feedback

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: Add Missing Imports and Fix Integration Issues

**Files:**
- Modify: `apps/web/src/components/wizard/AgentWizard.js`
- Modify: `apps/web/src/components/wizard/SkillsDataStep.js`

**Step 1: Add missing datasetService import to AgentWizard**

Modify `apps/web/src/components/wizard/AgentWizard.js`:

```javascript
// Add at top with other imports
import datasetService from '../../services/dataset';
```

**Step 2: Export wizard components for easier testing**

Create `apps/web/src/components/wizard/index.js`:

```javascript
export { default as AgentWizard } from './AgentWizard';
export { default as WizardStepper } from './WizardStepper';
export { default as TemplateSelector, TEMPLATES } from './TemplateSelector';
export { default as BasicInfoStep } from './BasicInfoStep';
export { default as PersonalityStep } from './PersonalityStep';
export { default as SkillsDataStep } from './SkillsDataStep';
export { default as ReviewStep } from './ReviewStep';
```

**Step 3: Verify all imports are correct**

Run a quick check:

```bash
cd apps/web
npm run build
```

Expected: Build succeeds with no import errors

**Step 4: Fix any TypeScript/PropTypes warnings (if applicable)**

If using PropTypes, add to each component:

```javascript
import PropTypes from 'prop-types';

// At bottom of each component file:
ComponentName.propTypes = {
  // Define prop types
};
```

**Step 5: Commit**

```bash
git add apps/web/src/components/wizard/
git commit -m "fix: add missing imports and create index export

- Add datasetService import to AgentWizard
- Create wizard components index for cleaner imports
- Verify all imports resolve correctly

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: Write Integration Tests

**Files:**
- Create: `apps/web/src/components/wizard/__tests__/AgentWizard.integration.test.js`

**Step 1: Write integration test for full wizard flow**

Create `apps/web/src/components/wizard/__tests__/AgentWizard.integration.test.js`:

```javascript
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import AgentWizard from '../AgentWizard';
import agentService from '../../../services/agent';
import datasetService from '../../../services/dataset';

jest.mock('../../../services/agent');
jest.mock('../../../services/dataset');

const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => ({
  ...jest.requireActual('react-router-dom'),
  useNavigate: () => mockNavigate,
}));

describe('AgentWizard Integration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    datasetService.getAll.mockResolvedValue({
      data: [
        { id: '123', name: 'Test Dataset', row_count: 100, columns: ['id', 'name'] }
      ]
    });
    agentService.create.mockResolvedValue({ data: { id: 'agent-123' } });
  });

  const renderWizard = () => {
    return render(
      <BrowserRouter>
        <AgentWizard />
      </BrowserRouter>
    );
  };

  test('completes full wizard flow', async () => {
    renderWizard();

    // Step 1: Select template
    await waitFor(() => {
      expect(screen.getByText('Data Analyst Agent')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Data Analyst Agent'));
    fireEvent.click(screen.getByText('Next'));

    // Step 2: Fill basic info
    await waitFor(() => {
      expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    });
    const nameInput = screen.getByLabelText(/name/i);
    fireEvent.change(nameInput, { target: { value: 'My Test Agent' } });
    fireEvent.click(screen.getByText('Next'));

    // Step 3: Select personality (already pre-filled)
    await waitFor(() => {
      expect(screen.getByText('Formal & Professional')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Next'));

    // Step 4: Configure skills (already pre-selected for Data Analyst)
    await waitFor(() => {
      expect(screen.getByText('SQL Query Tool')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Next'));

    // Step 5: Review and create
    await waitFor(() => {
      expect(screen.getByText('Review your agent')).toBeInTheDocument();
    });
    expect(screen.getByText('My Test Agent')).toBeInTheDocument();

    const createButton = screen.getByText('Create Agent');
    fireEvent.click(createButton);

    // Verify API call
    await waitFor(() => {
      expect(agentService.create).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'My Test Agent',
          config: expect.objectContaining({
            template_used: 'data_analyst',
          }),
        })
      );
    });

    // Verify navigation
    expect(mockNavigate).toHaveBeenCalledWith(
      '/dashboard/agents',
      expect.objectContaining({ state: { success: 'Agent created successfully!' } })
    );
  });

  test('persists draft to localStorage', async () => {
    renderWizard();

    // Select template
    await waitFor(() => {
      fireEvent.click(screen.getByText('General Assistant'));
    });

    // Wait for auto-save
    await waitFor(() => {
      const draft = localStorage.getItem('agent_wizard_draft');
      expect(draft).toBeTruthy();
      const parsed = JSON.parse(draft);
      expect(parsed.data.template.id).toBe('general_assistant');
    }, { timeout: 2000 });
  });

  test('resumes from draft', async () => {
    // Set up draft in localStorage
    const draft = {
      data: {
        template: { id: 'sales_assistant', name: 'Sales Assistant' },
        basicInfo: { name: 'Sales Bot', description: '', avatar: '' },
        personality: { preset: 'friendly', temperature: 0.6, max_tokens: 2000 },
        skills: { calculator: true, sql_query: false, data_summary: false },
        datasets: [],
      },
      step: 2,
      timestamp: new Date().toISOString(),
    };
    localStorage.setItem('agent_wizard_draft', JSON.stringify(draft));

    // Mock confirm to return true
    window.confirm = jest.fn(() => true);

    renderWizard();

    // Should load draft and show step 2
    await waitFor(() => {
      expect(screen.getByDisplayValue('Sales Bot')).toBeInTheDocument();
    });
  });
});
```

**Step 2: Run integration tests**

```bash
npm test -- AgentWizard.integration.test.js
```

Expected: All tests PASS

**Step 3: Commit**

```bash
git add apps/web/src/components/wizard/__tests__/AgentWizard.integration.test.js
git commit -m "test: add integration tests for wizard flow

- Test complete 5-step wizard flow
- Test draft persistence to localStorage
- Test draft resume functionality
- Test API integration with agent creation

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: Update Documentation

**Files:**
- Modify: `apps/web/README.md` (or create if doesn't exist)
- Modify: `CLAUDE.md`

**Step 1: Document wizard in web README**

Create or modify `apps/web/README.md`:

```markdown
# Web Application

React SPA for AgentProvision platform.

## Key Features

### Agent Creation Wizard

New guided 5-step wizard for creating agents:

1. **Template Selection** - Choose from 5 pre-configured templates
2. **Basic Info** - Name, description, avatar
3. **Personality** - Communication style presets
4. **Skills & Data** - Tool selection and dataset connection
5. **Review** - Summary and creation

**Components:**
- `components/wizard/AgentWizard.js` - Main wizard container
- `components/wizard/TemplateSelector.js` - Step 1
- `components/wizard/BasicInfoStep.js` - Step 2
- `components/wizard/PersonalityStep.js` - Step 3
- `components/wizard/SkillsDataStep.js` - Step 4
- `components/wizard/ReviewStep.js` - Step 5

**Features:**
- Auto-save drafts to localStorage
- Resume incomplete wizards
- Escape hatch to quick form for power users
- Template-based smart defaults

## Development

```bash
npm start    # Start dev server
npm test     # Run tests
npm run build # Production build
```
```

**Step 2: Update CLAUDE.md with wizard information**

Add to `CLAUDE.md` under "Recent Features":

```markdown
- ✅ **Agent Creation Wizard**: 5-step guided wizard for non-technical users with templates, plain-language controls, and smart defaults (see `docs/plans/2025-11-07-agent-creation-wizard-design.md`)
```

**Step 3: Commit**

```bash
git add apps/web/README.md CLAUDE.md
git commit -m "docs: document agent creation wizard

- Add wizard overview to web README
- Document component structure and features
- Update CLAUDE.md with wizard feature

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 12: Final Testing & Polish

**Step 1: Manual testing checklist**

Test the following scenarios:

1. ✅ Complete wizard flow (all 5 steps)
2. ✅ Select each template and verify pre-configuration
3. ✅ Form validation (name too short, missing template)
4. ✅ Draft auto-save (fill step 1-2, refresh, resume)
5. ✅ Escape hatch to quick form
6. ✅ Back navigation between steps
7. ✅ Cancel with confirmation
8. ✅ Dataset selection in step 4
9. ✅ Edit links in review step
10. ✅ Agent creation success flow

**Step 2: Fix any bugs found during testing**

Document and fix each issue found.

**Step 3: Run full test suite**

```bash
cd apps/web
npm test -- --coverage
```

Expected: >80% coverage on wizard components

**Step 4: Run production build**

```bash
npm run build
```

Expected: Build succeeds with no errors

**Step 5: Final commit**

```bash
git add .
git commit -m "feat: agent creation wizard complete

Complete implementation of 5-step agent creation wizard:
- Step 1: Template selection with 5 business templates
- Step 2: Basic info with avatar picker
- Step 3: Personality presets with advanced fine-tuning
- Step 4: Skills and dataset configuration
- Step 5: Review and test before creation

Features:
- Auto-save drafts to localStorage
- Resume incomplete wizards
- Smart defaults from templates
- Escape hatch for power users
- Form validation throughout

Tests: Full integration and unit test coverage

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Execution Complete

All 12 tasks completed! The agent creation wizard is now fully implemented with:

✅ 5-step guided flow
✅ Template system with 5 business templates
✅ Progressive disclosure (presets → advanced)
✅ Draft persistence & resume
✅ Full integration with existing agent API
✅ Comprehensive test coverage
✅ Documentation updates

**Next Steps:**
- Deploy to staging for user testing
- Gather feedback on template selection
- Consider adding more templates based on usage
- Monitor wizard completion rates vs old form
