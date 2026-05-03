import { render, screen } from '@testing-library/react';
import ReviewStep from '../ReviewStep';

describe('ReviewStep', () => {
  const mockWizardData = {
    template: { name: 'Data Analyst Agent', icon: 'BarChart' },
    basicInfo: { name: 'My Analyst', description: 'Analyzes data', avatar: '📊' },
    personality: { preset: 'formal', temperature: 0.4, max_tokens: 2000 },
    skills: { lead_scoring: true },
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

  test('shows enabled skills using friendly names when available', () => {
    render(<ReviewStep wizardData={mockWizardData} datasets={mockDatasets} onEdit={jest.fn()} />);
    expect(screen.getByText('Lead Scoring')).toBeInTheDocument();
  });

  test('renders the Skills section header', () => {
    render(<ReviewStep wizardData={mockWizardData} datasets={mockDatasets} onEdit={jest.fn()} />);
    expect(screen.getByText('Skills')).toBeInTheDocument();
  });

  test('shows edit links for each section', () => {
    render(<ReviewStep wizardData={mockWizardData} datasets={mockDatasets} onEdit={jest.fn()} />);
    const editLinks = screen.getAllByText('Edit');
    expect(editLinks.length).toBeGreaterThan(0);
  });

  test('falls back to "No special tools enabled" when skills empty', () => {
    const emptyData = { ...mockWizardData, skills: {} };
    render(<ReviewStep wizardData={emptyData} datasets={mockDatasets} onEdit={jest.fn()} />);
    expect(screen.getByText(/No special tools enabled/i)).toBeInTheDocument();
  });
});
