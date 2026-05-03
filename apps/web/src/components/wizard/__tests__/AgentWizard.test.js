import { render, screen } from '@testing-library/react';
import AgentWizard from '../AgentWizard';
import { ToastProvider } from '../../common/Toast';

jest.mock('react-router-dom');

// Surface skills service mock so SkillsDataStep can resolve a list cleanly,
// even though we never reach step 4 in these tests.
jest.mock('../../../services/skills', () => ({
  getFileSkills: jest.fn(() => Promise.resolve({ data: { skills: [] } })),
}));

const renderWizard = () =>
  render(
    <ToastProvider>
      <AgentWizard />
    </ToastProvider>
  );

describe('AgentWizard', () => {
  test('renders wizard stepper', () => {
    renderWizard();
    expect(screen.getByText('Template')).toBeInTheDocument();
  });

  test('shows step 1 by default', () => {
    renderWizard();
    expect(screen.getByText('What type of agent do you want to create?')).toBeInTheDocument();
  });

  test('renders Cancel button', () => {
    renderWizard();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  test('hides Back button on step 1', () => {
    renderWizard();
    expect(screen.queryByText('Back')).not.toBeInTheDocument();
  });
});
