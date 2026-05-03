import { render, screen, fireEvent } from '@testing-library/react';
import TemplateSelector from '../TemplateSelector';

describe('TemplateSelector', () => {
  const mockOnSelect = jest.fn();

  beforeEach(() => {
    mockOnSelect.mockClear();
  });

  test('renders core templates', () => {
    render(<TemplateSelector onSelect={mockOnSelect} />);
    expect(screen.getByText('Customer Support Agent')).toBeInTheDocument();
    expect(screen.getByText('Data Analyst Agent')).toBeInTheDocument();
    expect(screen.getByText('Sales Assistant')).toBeInTheDocument();
  });

  test('calls onSelect when a template card is clicked', () => {
    render(<TemplateSelector onSelect={mockOnSelect} />);
    const card = screen.getByText('Customer Support Agent').closest('.template-card');
    fireEvent.click(card);
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
