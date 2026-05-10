import { render, screen, fireEvent, waitFor, within, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SkillsPage from '../SkillsPage';

// ── Boundary mocks ────────────────────────────────────────────────────
jest.mock('../../services/skills', () => ({
  __esModule: true,
  getFileSkills: jest.fn(),
  createFileSkill: jest.fn(),
  updateFileSkill: jest.fn(),
  forkFileSkill: jest.fn(),
  deleteFileSkill: jest.fn(),
  executeFileSkill: jest.fn(),
  getSkillVersions: jest.fn(),
  importClaudeCodeSkill: jest.fn(),
  getMcpManifest: jest.fn(),
  exportSkill: jest.fn(),
}));

jest.mock('../../components/Layout', () => ({ children }) => <div>{children}</div>);

jest.mock('react-markdown', () => ({ children }) => <div>{children}</div>);
jest.mock('remark-gfm', () => () => {});

// Stable t() identity — SkillsPage uses `t` in a useCallback dep array,
// so a fresh t per render cancels and re-fires the initial fetch. Pin it
// to a single function reference.
jest.mock('react-i18next', () => {
  const t = (key, opts) => {
    if (typeof opts === 'string') return opts;
    if (opts && typeof opts === 'object') {
      if (opts.defaultValue) return opts.defaultValue;
      return key + ': ' + Object.values(opts).join(',');
    }
    return key;
  };
  const tu = { t };
  return {
    useTranslation: () => tu,
  };
});

const skillsApi = require('../../services/skills');

const sampleSkills = [
  {
    name: 'sql_query',
    slug: 'sql_query',
    description: 'Run a SQL query',
    engine: 'python',
    category: 'data',
    tier: 'native',
    version: '1.0',
    auto_trigger: 'when user asks for data',
    inputs: [{ name: 'query', type: 'string', required: true }],
    tags: ['sql', 'data'],
    chain_to: [],
  },
  {
    name: 'my_custom_skill',
    slug: 'my_custom_skill',
    description: 'Tenant-authored skill',
    engine: 'markdown',
    category: 'general',
    tier: 'custom',
    version: '1.0',
    inputs: [],
    tags: [],
    chain_to: [],
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <SkillsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  skillsApi.getFileSkills.mockResolvedValue({ data: sampleSkills });
  skillsApi.createFileSkill.mockResolvedValue({ data: {} });
  skillsApi.updateFileSkill.mockResolvedValue({ data: {} });
  skillsApi.forkFileSkill.mockResolvedValue({ data: {} });
  skillsApi.deleteFileSkill.mockResolvedValue({ data: {} });
  skillsApi.executeFileSkill.mockResolvedValue({ data: { result: 'ok' } });
  skillsApi.importClaudeCodeSkill.mockResolvedValue({ data: {} });
  skillsApi.getMcpManifest.mockResolvedValue({
    data: {
      server_url: 'http://example.com/mcp',
      tenant_id: 'tenant-abc',
      tools: [{ name: 't1' }, { name: 't2' }],
    },
  });
  skillsApi.exportSkill.mockResolvedValue({ data: 'exported content' });
  // jsdom provides createObjectURL etc., but not always — stub them so the
  // export path doesn't crash.
  if (!window.URL.createObjectURL) {
    window.URL.createObjectURL = jest.fn(() => 'blob:fake');
    window.URL.revokeObjectURL = jest.fn();
  }
});

describe('SkillsPage', () => {
  test('renders the header and loads skills on mount', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    // Native tab is the default — only sql_query renders.
    expect(await screen.findByText('sql_query')).toBeInTheDocument();
    expect(screen.queryByText('my_custom_skill')).not.toBeInTheDocument();
  });

  test('switches to the My Skills tab and shows tenant-authored skills', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    fireEvent.click(screen.getByRole('tab', { name: /tabs\.mySkills/ }));
    expect(await screen.findByText('my_custom_skill')).toBeInTheDocument();
    expect(screen.queryByText('sql_query')).not.toBeInTheDocument();
  });

  test('search filter narrows the visible skills', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    const search = screen.getByPlaceholderText('search.placeholder');
    fireEvent.change(search, { target: { value: 'sql' } });
    // Native tab still shows sql_query
    expect(screen.getByText('sql_query')).toBeInTheDocument();
  });

  test('category chips restrict visible skills', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    // sql_query is "data" category — toggling "general" should hide it.
    const generalChips = screen.getAllByRole('button', {
      name: /categories\.general/,
    });
    fireEvent.click(generalChips[0]);
    await waitFor(() =>
      expect(screen.queryByText('sql_query')).not.toBeInTheDocument(),
    );
  });

  test('opens the create skill modal', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    fireEvent.click(screen.getByRole('button', { name: /createSkill/ }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/createSkill/)).toBeInTheDocument();
  });

  test('create skill button is disabled when name is empty', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    fireEvent.click(screen.getByRole('button', { name: /createSkill/ }));
    const dialog = await screen.findByRole('dialog');
    // The footer Create button is disabled when the name field is empty.
    const createBtn = within(dialog).getByRole('button', { name: /create/i });
    expect(createBtn).toBeDisabled();
  });

  test('creating a markdown skill calls createFileSkill with the payload', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    fireEvent.click(screen.getByRole('button', { name: /createSkill/ }));
    const dialog = await screen.findByRole('dialog');
    const nameInput = within(dialog).getByPlaceholderText('form.namePlaceholder');
    fireEvent.change(nameInput, { target: { value: 'my_new_skill' } });
    // Default markdown script has {{input_name}} placeholders that fail
    // validation when no inputs are declared. Clear the script body so the
    // payload save path is exercised.
    const textareas = within(dialog).getAllByRole('textbox');
    // The last textarea is the script body (description and others come first).
    const scriptArea = textareas[textareas.length - 1];
    fireEvent.change(scriptArea, { target: { value: '# Plain markdown body, no placeholders.' } });
    const submitBtn = within(dialog).getByRole('button', { name: 'create' });
    fireEvent.click(submitBtn);
    await waitFor(() => {
      expect(skillsApi.createFileSkill).toHaveBeenCalled();
    });
    const payload = skillsApi.createFileSkill.mock.calls[0][0];
    expect(payload.name).toBe('my_new_skill');
    expect(payload.engine).toBe('markdown');
  });

  test('shows error when createFileSkill fails', async () => {
    skillsApi.createFileSkill.mockRejectedValue({
      response: { data: { detail: 'create boom' } },
    });
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    fireEvent.click(screen.getByRole('button', { name: /createSkill/ }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByPlaceholderText('form.namePlaceholder'), {
      target: { value: 'oops' },
    });
    const textareas = within(dialog).getAllByRole('textbox');
    fireEvent.change(textareas[textareas.length - 1], {
      target: { value: '# valid markdown' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'create' }));
    expect(await screen.findByText('create boom')).toBeInTheDocument();
  });

  test('opens the import skill modal', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    fireEvent.click(screen.getByRole('button', { name: /actions\.import/ }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/SKILL.md content/)).toBeInTheDocument();
  });

  test('importing a SKILL.md calls importClaudeCodeSkill', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    fireEvent.click(screen.getByRole('button', { name: /actions\.import/ }));
    const dialog = await screen.findByRole('dialog');
    const textarea = within(dialog).getByRole('textbox');
    fireEvent.change(textarea, {
      target: { value: '---\nname: imported\ndescription: x\n---\n# body' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Import' }));
    await waitFor(() => {
      expect(skillsApi.importClaudeCodeSkill).toHaveBeenCalledWith(
        expect.stringContaining('imported'),
        false,
      );
    });
  });

  test('clicking Try It opens the execute modal', async () => {
    renderPage();
    const card = await screen.findByText('sql_query');
    // The Try-It button lives on the same card as the skill title.
    const article = card.closest('article');
    const tryBtn = within(article).getByRole('button', { name: /tryIt/ });
    fireEvent.click(tryBtn);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    // Skill input field renders for "query".
    expect(await screen.findByText('query')).toBeInTheDocument();
  });

  test('executing a skill calls executeFileSkill with inputs', async () => {
    renderPage();
    const card = await screen.findByText('sql_query');
    const article = card.closest('article');
    fireEvent.click(within(article).getByRole('button', { name: /tryIt/ }));
    const dialog = await screen.findByRole('dialog');
    const input = within(dialog).getByPlaceholderText(
      /execute\.inputValue/,
    );
    fireEvent.change(input, { target: { value: 'SELECT 1' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /execute\.submit/ }));
    await waitFor(() => {
      expect(skillsApi.executeFileSkill).toHaveBeenCalledWith('sql_query', {
        query: 'SELECT 1',
      });
    });
  });

  test('delete on a custom skill confirms and calls deleteFileSkill', async () => {
    const confirmSpy = jest
      .spyOn(window, 'confirm')
      .mockImplementation(() => true);
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    fireEvent.click(screen.getByRole('tab', { name: /tabs\.mySkills/ }));
    await screen.findByText('my_custom_skill');
    // Open the action dropdown and click Delete.
    // The Dropdown.Toggle is inside the card; click the ellipsis button by role.
    const ellipsis = screen.getAllByRole('button').find(
      (b) => b.classList.contains('dropdown-toggle'),
    );
    fireEvent.click(ellipsis);
    const deleteItem = await screen.findByText(/actions\.delete/);
    fireEvent.click(deleteItem);
    await waitFor(() => {
      expect(skillsApi.deleteFileSkill).toHaveBeenCalledWith('my_custom_skill');
    });
    confirmSpy.mockRestore();
  });

  test('opens MCP connect modal and loads manifest', async () => {
    renderPage();
    await waitFor(() => expect(skillsApi.getFileSkills).toHaveBeenCalled());
    await screen.findByText('sql_query');
    fireEvent.click(screen.getByRole('button', { name: /mcp\.connectExternal/ }));
    await waitFor(() => expect(skillsApi.getMcpManifest).toHaveBeenCalled());
    // Server URL field renders the manifest's URL.
    expect(
      await screen.findByDisplayValue('http://example.com/mcp'),
    ).toBeInTheDocument();
  });

  test('shows the empty state when no skills load', async () => {
    skillsApi.getFileSkills.mockResolvedValue({ data: [] });
    renderPage();
    expect(await screen.findByText('noSkills')).toBeInTheDocument();
  });

  test('handles getFileSkills error gracefully', async () => {
    skillsApi.getFileSkills.mockRejectedValue(new Error('boom'));
    const errSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    renderPage();
    expect(await screen.findByText('errors.load')).toBeInTheDocument();
    errSpy.mockRestore();
  });
});
