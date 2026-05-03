import { memoryService } from '../memory';
import api from '../api';

jest.mock('../api');

describe('memoryService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockResolvedValue({ data: { items: [] } });
    api.post.mockResolvedValue({ data: { id: 'x' } });
    api.put.mockResolvedValue({ data: {} });
    api.patch.mockResolvedValue({ data: {} });
    api.delete.mockResolvedValue({ data: {} });
  });

  test('getMemories hits agent-scoped endpoint', async () => {
    await memoryService.getMemories('agent-1');
    expect(api.get).toHaveBeenCalledWith('/memories/agent/agent-1');
  });

  test('getEntities builds a query with filters and defaults', async () => {
    await memoryService.getEntities();
    expect(api.get.mock.calls[0][0]).toMatch(/skip=0/);
    expect(api.get.mock.calls[0][0]).toMatch(/limit=50/);

    await memoryService.getEntities({ entityType: 'person', category: 'sales', status: 'active' });
    const url = api.get.mock.calls[1][0];
    expect(url).toContain('entity_type=person');
    expect(url).toContain('category=sales');
    expect(url).toContain('status=active');
  });

  test('searchEntities encodes the query', async () => {
    await memoryService.searchEntities('alice');
    const url = api.get.mock.calls[0][0];
    expect(url).toContain('/knowledge/entities/search?');
    expect(url).toContain('q=alice');
  });

  test('createEntity + updateEntity + deleteEntity', async () => {
    await memoryService.createEntity({ name: 'X' });
    expect(api.post).toHaveBeenCalledWith('/knowledge/entities', { name: 'X' });

    await memoryService.updateEntity('e1', { name: 'Y' });
    expect(api.put).toHaveBeenCalledWith('/knowledge/entities/e1', { name: 'Y' });

    await memoryService.deleteEntity('e1');
    expect(api.delete).toHaveBeenCalledWith('/knowledge/entities/e1');
  });

  test('bulkDeleteEntities throws when some fail', async () => {
    api.delete.mockImplementation((url) =>
      url.endsWith('/2') ? Promise.reject(new Error('boom')) : Promise.resolve({ data: {} })
    );
    await expect(memoryService.bulkDeleteEntities(['1', '2', '3'])).rejects.toThrow(/Failed to delete 1 of 3/);
  });

  test('updateEntityStatus and scoreEntity', async () => {
    await memoryService.updateEntityStatus('e1', 'archived');
    expect(api.put).toHaveBeenCalledWith('/knowledge/entities/e1/status', { status: 'archived' });

    await memoryService.scoreEntity('e1');
    expect(api.post).toHaveBeenCalledWith('/knowledge/entities/e1/score');

    await memoryService.scoreEntity('e1', 'rubric-7');
    expect(api.post).toHaveBeenCalledWith('/knowledge/entities/e1/score?rubric_id=rubric-7');
  });

  test('relations CRUD', async () => {
    await memoryService.getAllRelations({ relationType: 'mentions' });
    expect(api.get.mock.calls[0][0]).toContain('relation_type=mentions');

    await memoryService.getRelations('e1');
    expect(api.get).toHaveBeenLastCalledWith('/knowledge/entities/e1/relations?direction=both');

    await memoryService.getRelations('e1', 'incoming');
    expect(api.get).toHaveBeenLastCalledWith('/knowledge/entities/e1/relations?direction=incoming');

    await memoryService.createRelation({ from: 'a', to: 'b' });
    expect(api.post).toHaveBeenCalledWith('/knowledge/relations', { from: 'a', to: 'b' });

    await memoryService.deleteRelation('r1');
    expect(api.delete).toHaveBeenCalledWith('/knowledge/relations/r1');
  });

  test('tenant memories + activity + episodes + stats endpoints', async () => {
    await memoryService.getTenantMemories({ memoryType: 'observation' });
    expect(api.get.mock.calls[0][0]).toContain('memory_type=observation');

    await memoryService.updateMemoryItem('m1', { tag: 'x' });
    expect(api.patch).toHaveBeenCalledWith('/memories/m1', { tag: 'x' });

    await memoryService.deleteMemoryItem('m1');
    expect(api.delete).toHaveBeenCalledWith('/memories/m1');

    await memoryService.getActivityFeed({ source: 'gmail', eventType: 'created' });
    const lastUrl = api.get.mock.calls[api.get.mock.calls.length - 1][0];
    expect(lastUrl).toContain('source=gmail');
    expect(lastUrl).toContain('event_type=created');

    await memoryService.getEpisodes({ sourceChannel: 'whatsapp', mood: 'happy' });
    const epsUrl = api.get.mock.calls[api.get.mock.calls.length - 1][0];
    expect(epsUrl).toContain('source_channel=whatsapp');
    expect(epsUrl).toContain('mood=happy');

    await memoryService.getMemoryStats();
    expect(api.get).toHaveBeenLastCalledWith('/memories/stats');
  });
});
