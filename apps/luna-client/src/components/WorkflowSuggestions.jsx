import React, { useState, useEffect, useCallback } from 'react';
import { apiJson } from '../api';

export default function WorkflowSuggestions({ visible, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(null);

  useEffect(() => {
    if (!visible) return;
    setLoading(true);
    apiJson('/api/v1/activities/patterns?days=7')
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [visible]);

  const createWorkflow = useCallback(async (suggestion) => {
    setCreating(suggestion.pattern);
    try {
      await apiJson('/api/v1/dynamic-workflows', {
        method: 'POST',
        body: JSON.stringify(suggestion.workflow_template),
      });
      // Remove from suggestions list
      setData(prev => ({
        ...prev,
        suggestions: prev.suggestions.filter(s => s.pattern !== suggestion.pattern),
      }));
    } catch (err) {
      console.error('Failed to create workflow:', err);
    } finally {
      setCreating(null);
    }
  }, []);

  if (!visible) return null;

  return (
    <div className="workflow-suggestions-panel">
      <div className="ws-header">
        <span>Workflow Suggestions</span>
        <button className="notif-close" onClick={onClose}>x</button>
      </div>
      <div className="ws-body">
        {loading && <p className="notif-empty">Analyzing your patterns...</p>}

        {data && data.suggestions?.length === 0 && !loading && (
          <div className="ws-empty">
            <p>No patterns detected yet.</p>
            <p className="ws-hint">Keep using your apps — Luna learns your routines and suggests automations after a few days.</p>
          </div>
        )}

        {data?.suggestions?.map(s => (
          <div key={s.pattern} className="ws-card">
            <div className="ws-pattern">
              {s.apps.map((app, i) => (
                <span key={i}>
                  <span className="ws-app">{app}</span>
                  {i < s.apps.length - 1 && <span className="ws-arrow">&rarr;</span>}
                </span>
              ))}
            </div>
            <p className="ws-desc">{s.suggestion}</p>
            <div className="ws-meta">
              <span>{s.frequency}x in the last week</span>
            </div>
            <button
              className="luna-btn luna-btn-sm ws-create"
              onClick={() => createWorkflow(s)}
              disabled={creating === s.pattern}
            >
              {creating === s.pattern ? 'Creating...' : 'Automate this'}
            </button>
          </div>
        ))}

        {data?.patterns?.time_of_day && Object.keys(data.patterns.time_of_day).length > 0 && (
          <div className="ws-section">
            <h4>Your Daily Rhythm</h4>
            {Object.entries(data.patterns.time_of_day).map(([period, apps]) => (
              <div key={period} className="ws-time-row">
                <span className="ws-period">{period}</span>
                <div className="ws-time-apps">
                  {apps.map((a, i) => (
                    <span key={i} className="memory-tag">{a.app} ({a.count})</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}

        {data && (
          <p className="ws-footer">{data.activity_count} events tracked over {data.period_days} days</p>
        )}
      </div>
    </div>
  );
}
