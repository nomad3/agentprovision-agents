import { render, screen, fireEvent } from '@testing-library/react';
import EntityCard from '../EntityCard';

jest.mock('../EntityDetail', () => ({ entity }) => (
  <div data-testid="entity-detail">{entity.name}-detail</div>
));

const sampleEntity = {
  id: 'e-1',
  name: 'Brett',
  category: 'person',
  status: 'active',
  score: 75,
  confidence: 0.82,
  description: 'Lead veterinary cardiologist at HealthPets',
};

describe('EntityCard', () => {
  test('renders the entity name and description', () => {
    render(
      <EntityCard
        entity={sampleEntity}
        isExpanded={false}
        isSelected={false}
        onToggleExpand={jest.fn()}
        onToggleSelect={jest.fn()}
      />,
    );
    expect(screen.getByText('Brett')).toBeInTheDocument();
    expect(screen.getByText('Lead veterinary cardiologist at HealthPets')).toBeInTheDocument();
  });

  test('renders the score badge when entity has a score', () => {
    render(
      <EntityCard
        entity={sampleEntity}
        isExpanded={false}
        isSelected={false}
        onToggleExpand={jest.fn()}
        onToggleSelect={jest.fn()}
      />,
    );
    expect(screen.getByText('75')).toBeInTheDocument();
  });

  test('shows the confidence percentage rounded to nearest int', () => {
    render(
      <EntityCard
        entity={sampleEntity}
        isExpanded={false}
        isSelected={false}
        onToggleExpand={jest.fn()}
        onToggleSelect={jest.fn()}
      />,
    );
    expect(screen.getByText('82%')).toBeInTheDocument();
  });

  test('clicking the header invokes onToggleExpand', () => {
    const onToggleExpand = jest.fn();
    render(
      <EntityCard
        entity={sampleEntity}
        isExpanded={false}
        isSelected={false}
        onToggleExpand={onToggleExpand}
        onToggleSelect={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByText('Brett'));
    expect(onToggleExpand).toHaveBeenCalledWith('e-1');
  });

  test('checkbox click invokes onToggleSelect (and stops propagation)', () => {
    const onToggleSelect = jest.fn();
    const onToggleExpand = jest.fn();
    render(
      <EntityCard
        entity={sampleEntity}
        isExpanded={false}
        isSelected={false}
        onToggleExpand={onToggleExpand}
        onToggleSelect={onToggleSelect}
      />,
    );
    fireEvent.click(screen.getByRole('checkbox'));
    expect(onToggleSelect).toHaveBeenCalledWith('e-1');
    // Stop propagation prevents the toggle-expand path.
    expect(onToggleExpand).not.toHaveBeenCalled();
  });

  test('renders EntityDetail when isExpanded is true', () => {
    render(
      <EntityCard
        entity={sampleEntity}
        isExpanded={true}
        isSelected={false}
        onToggleExpand={jest.fn()}
        onToggleSelect={jest.fn()}
      />,
    );
    expect(screen.getByTestId('entity-detail')).toBeInTheDocument();
    // Description card hides when expanded.
    expect(
      screen.queryByText('Lead veterinary cardiologist at HealthPets'),
    ).not.toBeInTheDocument();
  });

  test('handles entities with no score and no description gracefully', () => {
    render(
      <EntityCard
        entity={{ id: 'e-2', name: 'Aremko', category: 'organization', status: 'active' }}
        isExpanded={false}
        isSelected={false}
        onToggleExpand={jest.fn()}
        onToggleSelect={jest.fn()}
      />,
    );
    expect(screen.getByText('Aremko')).toBeInTheDocument();
    // Confidence falls back to 0%.
    expect(screen.getByText('0%')).toBeInTheDocument();
  });
});
