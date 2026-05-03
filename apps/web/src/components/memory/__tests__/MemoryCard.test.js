import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MemoryCard from '../MemoryCard';

describe('MemoryCard', () => {
  const baseMemory = {
    id: 'm1',
    content: 'Original note',
    memory_type: 'observation',
    source: 'gmail',
    created_at: '2026-04-01T00:00:00Z',
    importance: 0.75,
  };

  test('renders content, source and importance', () => {
    render(<MemoryCard memory={baseMemory} onUpdate={() => {}} onDelete={() => {}} />);
    expect(screen.getByText('Original note')).toBeInTheDocument();
    expect(screen.getByText('gmail')).toBeInTheDocument();
    expect(screen.getByText(/75% importance/)).toBeInTheDocument();
  });

  test('clicking edit reveals the textarea', () => {
    render(<MemoryCard memory={baseMemory} onUpdate={() => {}} onDelete={() => {}} />);
    fireEvent.click(screen.getByTitle('Edit'));
    expect(screen.getByDisplayValue('Original note')).toBeInTheDocument();
  });

  test('save calls onUpdate with the new content', async () => {
    const onUpdate = jest.fn().mockResolvedValue(undefined);
    render(<MemoryCard memory={baseMemory} onUpdate={onUpdate} onDelete={() => {}} />);
    fireEvent.click(screen.getByTitle('Edit'));
    fireEvent.change(screen.getByDisplayValue('Original note'), { target: { value: 'Updated note' } });
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith('m1', { content: 'Updated note' }));
  });

  test('cancel reverts edits and exits editing', () => {
    render(<MemoryCard memory={baseMemory} onUpdate={() => {}} onDelete={() => {}} />);
    fireEvent.click(screen.getByTitle('Edit'));
    fireEvent.change(screen.getByDisplayValue('Original note'), { target: { value: 'Trash' } });
    fireEvent.click(screen.getByText('Cancel'));
    expect(screen.getByText('Original note')).toBeInTheDocument();
  });

  test('save is a no-op when content is empty', async () => {
    const onUpdate = jest.fn();
    render(<MemoryCard memory={baseMemory} onUpdate={onUpdate} onDelete={() => {}} />);
    fireEvent.click(screen.getByTitle('Edit'));
    fireEvent.change(screen.getByDisplayValue('Original note'), { target: { value: '   ' } });
    fireEvent.click(screen.getByText('Save'));
    expect(onUpdate).not.toHaveBeenCalled();
  });

  test('delete fires onDelete with the memory id', () => {
    const onDelete = jest.fn();
    render(<MemoryCard memory={baseMemory} onUpdate={() => {}} onDelete={onDelete} />);
    fireEvent.click(screen.getByTitle('Delete'));
    expect(onDelete).toHaveBeenCalledWith('m1');
  });
});
