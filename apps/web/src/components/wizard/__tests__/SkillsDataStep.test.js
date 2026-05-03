import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SkillsDataStep from '../SkillsDataStep';
import { getFileSkills } from '../../../services/skills';

jest.mock('../../../services/skills', () => ({
  getFileSkills: jest.fn(),
}));

describe('SkillsDataStep', () => {
  const mockOnChange = jest.fn();
  const defaultData = { skills: {}, datasets: [] };

  const mockSkills = [
    { slug: 'lead_scoring', name: 'Lead Scoring', category: 'sales', engine: 'tool', description: 'Scores leads against a rubric.' },
    { slug: 'sql_query', name: 'SQL Query', category: 'data', engine: 'tool', description: 'Runs a SQL query.' },
  ];

  beforeEach(() => {
    mockOnChange.mockClear();
    getFileSkills.mockResolvedValue({ data: { skills: mockSkills } });
  });

  test('renders skills returned by the registry', async () => {
    render(<SkillsDataStep data={defaultData} onChange={mockOnChange} />);
    await waitFor(() => {
      expect(screen.getByText('Lead Scoring')).toBeInTheDocument();
      expect(screen.getByText('SQL Query')).toBeInTheDocument();
    });
  });

  test('shows pre-selected skills as checked', async () => {
    const dataWithSkills = { skills: { lead_scoring: true }, datasets: [] };
    render(<SkillsDataStep data={dataWithSkills} onChange={mockOnChange} />);
    await waitFor(() => {
      const toggle = screen.getByLabelText('Lead Scoring');
      expect(toggle).toBeChecked();
    });
  });

  test('calls onChange when a skill toggle is clicked', async () => {
    render(<SkillsDataStep data={defaultData} onChange={mockOnChange} />);
    const toggle = await screen.findByLabelText('Lead Scoring');
    fireEvent.click(toggle);
    expect(mockOnChange).toHaveBeenCalledWith(expect.objectContaining({
      skills: expect.objectContaining({ lead_scoring: true }),
    }));
  });

  test('renders search input and category filters', async () => {
    render(<SkillsDataStep data={defaultData} onChange={mockOnChange} />);
    await waitFor(() => expect(screen.getByPlaceholderText(/Search skills/i)).toBeInTheDocument());
    expect(screen.getByText('All')).toBeInTheDocument();
  });

  test('filters skills by search query', async () => {
    render(<SkillsDataStep data={defaultData} onChange={mockOnChange} />);
    const search = await screen.findByPlaceholderText(/Search skills/i);
    fireEvent.change(search, { target: { value: 'lead' } });
    expect(screen.getByText('Lead Scoring')).toBeInTheDocument();
    expect(screen.queryByText('SQL Query')).not.toBeInTheDocument();
  });

  test('shows empty-state message when nothing matches', async () => {
    render(<SkillsDataStep data={defaultData} onChange={mockOnChange} />);
    const search = await screen.findByPlaceholderText(/Search skills/i);
    fireEvent.change(search, { target: { value: 'zzz-no-match-zzz' } });
    expect(screen.getByText(/No skills match your search/i)).toBeInTheDocument();
  });
});
