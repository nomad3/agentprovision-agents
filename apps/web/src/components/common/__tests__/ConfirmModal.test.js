import { render, screen, fireEvent } from '@testing-library/react';
import ConfirmModal from '../ConfirmModal';

describe('ConfirmModal', () => {
  test('does not render when show=false', () => {
    render(<ConfirmModal show={false} title="t" message="m" />);
    expect(screen.queryByText('t')).not.toBeInTheDocument();
  });

  test('renders title and message when shown', () => {
    render(<ConfirmModal show title="Delete?" message="This is permanent" />);
    expect(screen.getByText('Delete?')).toBeInTheDocument();
    expect(screen.getByText('This is permanent')).toBeInTheDocument();
  });

  test('uses custom button labels', () => {
    render(
      <ConfirmModal
        show
        title="t"
        message="m"
        confirmText="Yes, delete"
        cancelText="Keep it"
      />
    );
    expect(screen.getByRole('button', { name: 'Yes, delete' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep it' })).toBeInTheDocument();
  });

  test('confirm button shows loading copy when confirmLoading', () => {
    render(<ConfirmModal show title="t" message="m" confirmLoading />);
    expect(screen.getByRole('button', { name: /Processing/ })).toBeDisabled();
  });

  test('clicking the confirm button calls onConfirm', () => {
    const onConfirm = jest.fn();
    render(<ConfirmModal show title="t" message="m" onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole('button', { name: /Confirm/ }));
    expect(onConfirm).toHaveBeenCalled();
  });

  test('clicking cancel calls onHide', () => {
    const onHide = jest.fn();
    render(<ConfirmModal show title="t" message="m" onHide={onHide} />);
    fireEvent.click(screen.getByRole('button', { name: /Cancel/ }));
    expect(onHide).toHaveBeenCalled();
  });
});
