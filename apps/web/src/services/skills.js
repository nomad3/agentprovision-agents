import api from './api';

export const skillsService = {
  getSkills: async (skillType) => {
    const params = {};
    if (skillType) params.skill_type = skillType;
    const response = await api.get('/skills', { params });
    return response.data;
  },

  getSkill: async (id) => {
    const response = await api.get(`/skills/${id}`);
    return response.data;
  },

  createSkill: async (data) => {
    const response = await api.post('/skills', data);
    return response.data;
  },

  updateSkill: async (id, data) => {
    const response = await api.put(`/skills/${id}`, data);
    return response.data;
  },

  deleteSkill: async (id) => {
    const response = await api.delete(`/skills/${id}`);
    return response.data;
  },

  executeSkill: async (id, entityId, params) => {
    const response = await api.post(`/skills/${id}/execute`, {
      entity_id: entityId,
      params: params || {},
    });
    return response.data;
  },

  getSkillExecutions: async (id) => {
    const response = await api.get(`/skills/${id}/executions`);
    return response.data;
  },

  cloneSkill: async (id) => {
    const response = await api.post(`/skills/${id}/clone`);
    return response.data;
  },
};
