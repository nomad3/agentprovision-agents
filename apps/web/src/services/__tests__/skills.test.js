import {
  skillsService,
  getFileSkills,
  createFileSkill,
  updateFileSkill,
  forkFileSkill,
  deleteFileSkill,
  executeFileSkill,
  getSkillVersions,
  importFromGithub,
  importClaudeCodeSkill,
  getMcpManifest,
  exportSkill,
} from '../skills';
import api from '../api';

jest.mock('../api');

describe('skillsService (DB tier)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockResolvedValue({ data: [] });
    api.post.mockResolvedValue({ data: { id: 'x' } });
    api.put.mockResolvedValue({ data: {} });
    api.delete.mockResolvedValue({ data: {} });
  });

  test('getSkills passes skill_type when given', async () => {
    await skillsService.getSkills();
    expect(api.get).toHaveBeenCalledWith('/skills', { params: {} });

    await skillsService.getSkills('coding');
    expect(api.get).toHaveBeenCalledWith('/skills', { params: { skill_type: 'coding' } });
  });

  test('CRUD endpoints', async () => {
    await skillsService.getSkill('s1');
    expect(api.get).toHaveBeenCalledWith('/skills/s1');

    await skillsService.createSkill({ name: 'X' });
    expect(api.post).toHaveBeenCalledWith('/skills', { name: 'X' });

    await skillsService.updateSkill('s1', { name: 'Y' });
    expect(api.put).toHaveBeenCalledWith('/skills/s1', { name: 'Y' });

    await skillsService.deleteSkill('s1');
    expect(api.delete).toHaveBeenCalledWith('/skills/s1');
  });

  test('executeSkill posts entity_id and params', async () => {
    await skillsService.executeSkill('s1', 'e1', { foo: 'bar' });
    expect(api.post).toHaveBeenCalledWith('/skills/s1/execute', {
      entity_id: 'e1',
      params: { foo: 'bar' },
    });

    await skillsService.executeSkill('s1', 'e1');
    expect(api.post).toHaveBeenLastCalledWith('/skills/s1/execute', {
      entity_id: 'e1',
      params: {},
    });
  });

  test('cloneSkill + getSkillExecutions', async () => {
    await skillsService.cloneSkill('s1');
    expect(api.post).toHaveBeenCalledWith('/skills/s1/clone');

    await skillsService.getSkillExecutions('s1');
    expect(api.get).toHaveBeenCalledWith('/skills/s1/executions');
  });
});

describe('skills library (file tier)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockResolvedValue({ data: [] });
    api.post.mockResolvedValue({ data: { ok: true } });
    api.put.mockResolvedValue({ data: {} });
    api.delete.mockResolvedValue({ data: {} });
  });

  test('getFileSkills builds query string from params', () => {
    getFileSkills();
    expect(api.get).toHaveBeenCalledWith('/skills/library');

    getFileSkills({ tier: 'native', category: 'data', search: 'sql' });
    const url = api.get.mock.calls[1][0];
    expect(url).toMatch(/^\/skills\/library\?/);
    expect(url).toContain('tier=native');
    expect(url).toContain('category=data');
    expect(url).toContain('search=sql');
  });

  test('library CRUD functions hit the right endpoints', () => {
    createFileSkill({ slug: 'x' });
    expect(api.post).toHaveBeenCalledWith('/skills/library/create', { slug: 'x' });

    updateFileSkill('x', { description: 'd' });
    expect(api.put).toHaveBeenCalledWith('/skills/library/x', { description: 'd' });

    forkFileSkill('x');
    expect(api.post).toHaveBeenCalledWith('/skills/library/x/fork');

    deleteFileSkill('x');
    expect(api.delete).toHaveBeenCalledWith('/skills/library/x');

    executeFileSkill('lead_scoring', { lead_id: '1' });
    expect(api.post).toHaveBeenCalledWith('/skills/library/execute', {
      skill_name: 'lead_scoring',
      inputs: { lead_id: '1' },
    });

    getSkillVersions('x');
    expect(api.get).toHaveBeenCalledWith('/skills/library/x/versions');

    importFromGithub('https://example.com/repo');
    expect(api.post).toHaveBeenCalledWith('/skills/library/import-github', {
      repo_url: 'https://example.com/repo',
    });

    importClaudeCodeSkill('---\nname: x\n---', true);
    expect(api.post).toHaveBeenCalledWith('/skills/library/import-claude-code', {
      content: '---\nname: x\n---',
      overwrite: true,
    });

    getMcpManifest();
    expect(api.get).toHaveBeenCalledWith('/skills/mcp-manifest');

    exportSkill('x', 'superpowers');
    expect(api.get).toHaveBeenCalledWith(
      '/skills/library/x/export',
      expect.objectContaining({ params: { format: 'superpowers' } })
    );
  });
});
