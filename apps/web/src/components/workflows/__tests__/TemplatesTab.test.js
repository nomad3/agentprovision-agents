import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import TemplatesTab from '../TemplatesTab';
import dynamicWorkflowService from '../../../services/dynamicWorkflowService';

jest.mock('../../../services/dynamicWorkflowService', () => ({
  __esModule: true,
  default: {
    browseTemplates: jest.fn(),
    installTemplate: jest.fn(),
  },
}));

const mockNavigate = jest.fn();
jest.mock('react-router-dom', () => {
  const actual = jest.requireActual('../../../__mocks__/react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

jest.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k, opts) => (opts?.count != null ? `${k}:${opts.count}` : k) }),
}));

describe('TemplatesTab', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders empty state when there are no templates', async () => {
    dynamicWorkflowService.browseTemplates.mockResolvedValue([]);
    render(<TemplatesTab />);
    expect(await screen.findByText('templates.noTemplates')).toBeInTheDocument();
  });

  test('renders one card per template', async () => {
    dynamicWorkflowService.browseTemplates.mockResolvedValue([
      { id: '1', name: 'Daily Briefing', description: 'Each morning', tier: 'native', trigger_config: { type: 'cron' }, definition: { steps: [{}, {}] } },
      { id: '2', name: 'Lead Pipeline', description: 'Score leads', tier: 'community', trigger_config: { type: 'event' }, definition: { steps: [] } },
    ]);
    render(<TemplatesTab />);
    expect(await screen.findByText('Daily Briefing')).toBeInTheDocument();
    expect(screen.getByText('Lead Pipeline')).toBeInTheDocument();
    expect(screen.getByText('Scheduled')).toBeInTheDocument();
    expect(screen.getByText('Event')).toBeInTheDocument();
  });

  test('clicking install fires installTemplate and navigates to the builder', async () => {
    dynamicWorkflowService.browseTemplates.mockResolvedValue([
      { id: 't1', name: 'Tpl', description: 'd', tier: 'native', trigger_config: { type: 'manual' }, definition: { steps: [] } },
    ]);
    dynamicWorkflowService.installTemplate.mockResolvedValue({ id: 'wf-99' });
    render(<TemplatesTab />);
    const installBtns = await screen.findAllByText(/templates.install/);
    fireEvent.click(installBtns[0]);
    await waitFor(() =>
      expect(dynamicWorkflowService.installTemplate).toHaveBeenCalledWith('t1')
    );
    await waitFor(() =>
      expect(mockNavigate).toHaveBeenCalledWith('/workflows/builder/wf-99')
    );
  });

  test('preview navigates without installing', async () => {
    dynamicWorkflowService.browseTemplates.mockResolvedValue([
      { id: 't1', name: 'Tpl', description: 'd', tier: 'native', trigger_config: { type: 'manual' }, definition: { steps: [] } },
    ]);
    render(<TemplatesTab />);
    const previewBtns = await screen.findAllByText(/templates.preview/);
    fireEvent.click(previewBtns[0]);
    expect(mockNavigate).toHaveBeenCalledWith('/workflows/builder/t1');
    expect(dynamicWorkflowService.installTemplate).not.toHaveBeenCalled();
  });
});
