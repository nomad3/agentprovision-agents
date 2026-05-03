import agentService from '../agent';
import api from '../api';

jest.mock('../api');

describe('agentService', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.get.mockResolvedValue({ data: {} });
    api.post.mockResolvedValue({ data: {} });
    api.put.mockResolvedValue({ data: {} });
    api.delete.mockResolvedValue({ data: {} });
  });

  test('CRUD endpoints route to /agents/', async () => {
    await agentService.getAll();
    expect(api.get).toHaveBeenCalledWith('/agents/');

    await agentService.getById('abc');
    expect(api.get).toHaveBeenCalledWith('/agents/abc');

    await agentService.create({ name: 'x' });
    expect(api.post).toHaveBeenCalledWith('/agents/', { name: 'x' });

    await agentService.update('abc', { name: 'y' });
    expect(api.put).toHaveBeenCalledWith('/agents/abc', { name: 'y' });

    await agentService.delete('abc');
    expect(api.delete).toHaveBeenCalledWith('/agents/abc');
  });

  test('discover passes capability and optional kind', async () => {
    await agentService.discover('search');
    expect(api.get).toHaveBeenCalledWith('/agents/discover', { params: { capability: 'search' } });

    await agentService.discover('search', 'external');
    expect(api.get).toHaveBeenCalledWith('/agents/discover', {
      params: { capability: 'search', kind: 'external' },
    });
  });

  test('createExternal + testTask call the right endpoints', async () => {
    await agentService.createExternal({ name: 'Ext' });
    expect(api.post).toHaveBeenCalledWith('/external-agents/', { name: 'Ext' });

    await agentService.testTask('e1', 'do something');
    expect(api.post).toHaveBeenCalledWith('/external-agents/e1/test-task', { task: 'do something' });
  });

  test('marketplace and import endpoints', async () => {
    await agentService.subscribeListing('listing-1');
    expect(api.post).toHaveBeenCalledWith('/agent-marketplace/subscribe', { listing_id: 'listing-1' });

    await agentService.listMarketplace();
    expect(api.get).toHaveBeenCalledWith('/agent-marketplace/listings', { params: {} });

    await agentService.listMarketplace('search');
    expect(api.get).toHaveBeenCalledWith('/agent-marketplace/listings', {
      params: { capability: 'search' },
    });

    await agentService.importAgent('yaml: 1', 'crew.yaml');
    expect(api.post).toHaveBeenCalledWith('/agents/import', {
      content: 'yaml: 1',
      filename: 'crew.yaml',
    });
  });
});
