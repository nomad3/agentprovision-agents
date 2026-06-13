import api from './api';

const workspaceService = {
  list: () => api.get('/workspaces'),
  catalog: () => api.get('/workspaces/catalog'),
  get: (slug) => api.get(`/workspaces/${encodeURIComponent(slug)}`),
  getWidget: (slug, widgetKey) => (
    api.get(`/workspaces/${encodeURIComponent(slug)}/widgets/${encodeURIComponent(widgetKey)}`)
  ),
};

export default workspaceService;
