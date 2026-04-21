import React, { useEffect, useState } from 'react';
import { Spinner } from 'react-bootstrap';
import { getActivityEventConfig } from './constants';
import { memoryService } from '../../services/memory';

const OverviewTab = () => {
  const [stats, setStats] = useState(null);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [statsData, activityData] = await Promise.all([
        memoryService.getMemoryStats(),
        memoryService.getActivityFeed({ limit: 10 }),
      ]);
      setStats(statsData);
      setActivity(activityData || []);
    } catch (err) {
      console.error('Failed to load overview:', err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="text-center py-5">
        <Spinner animation="border" size="sm" className="text-muted" />
      </div>
    );
  }

  const statTiles = [
    { label: 'Entities', value: stats?.total_entities || 0 },
    { label: 'Memories', value: stats?.total_memories || 0 },
    { label: 'Relations', value: stats?.total_relations || 0 },
    { label: 'Observations', value: stats?.total_observations || 0 },
    { label: 'Episodes', value: stats?.total_episodes || 0 },
    { label: 'Learned Today', value: stats?.learned_today || 0 },
  ];

  const byCategory = stats?.by_category || {};

  const formatTime = (dateStr) => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  };

  return (
    <div className="overview-tab">
      {/* Summary tiles */}
      <div className="row g-3 mb-4">
        {statTiles.map((tile) => (
          <div key={tile.label} className="col-6 col-md-4 col-lg-2">
            <article className="ap-card">
              <div className="ap-card-body" style={{ padding: 'var(--ap-space-4)' }}>
                <div className="ap-section-label">{tile.label}</div>
                <div style={{ fontSize: 'var(--ap-fs-xl)', fontWeight: 700, color: 'var(--ap-text)', lineHeight: 1 }}>
                  {tile.value}
                </div>
              </div>
            </article>
          </div>
        ))}
      </div>

      {/* Per-category entity counts */}
      {Object.keys(byCategory).length > 0 && (
        <div className="mb-4">
          <div className="ap-section-label" style={{ marginBottom: 'var(--ap-space-3)' }}>By Category</div>
          <div className="row g-3">
            {Object.entries(byCategory).map(([cat, count]) => (
              <div key={cat} className="col-6 col-md-3">
                <article className="ap-card">
                  <div className="ap-card-body" style={{ padding: 'var(--ap-space-4)' }}>
                    <div className="ap-section-label">{cat}</div>
                    <div style={{ fontSize: 'var(--ap-fs-xl)', fontWeight: 700, color: 'var(--ap-text)', lineHeight: 1 }}>
                      {count}
                    </div>
                  </div>
                </article>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Memory Health */}
      <div className="overview-section">
        <h6 className="overview-section-title">Memory Health</h6>
        <div className="health-bars">
          {[
            { label: 'Entities', value: stats?.total_entities || 0, max: 100, color: '#60a5fa' },
            { label: 'Relations', value: stats?.total_relations || 0, max: 50, color: '#a78bfa' },
            { label: 'Memories', value: stats?.total_memories || 0, max: 50, color: '#f472b6' },
            { label: 'Observations', value: stats?.total_observations || 0, max: 200, color: '#fbbf24' },
            { label: 'Episodes', value: stats?.total_episodes || 0, max: 50, color: '#38bdf8' },
          ].map((bar) => (
            <div key={bar.label} className="health-bar-row">
              <span className="health-bar-label">{bar.label}</span>
              <div className="health-bar-track">
                <div
                  className="health-bar-fill"
                  style={{
                    width: `${Math.min(100, (bar.value / bar.max) * 100)}%`,
                    background: bar.color,
                  }}
                />
              </div>
              <span className="health-bar-value" style={{ color: bar.color }}>{bar.value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Activity */}
      <div className="overview-section">
        <h6 className="overview-section-title">Recent Activity</h6>
        {activity.length === 0 ? (
          <p className="text-muted small">No activity yet. Chat with Luna to start building memory.</p>
        ) : (
          <div className="activity-list">
            {activity.map((item) => {
              const cfg = getActivityEventConfig(item.event_type);
              const EventIcon = cfg.icon;
              return (
                <div key={item.id} className="activity-item">
                  <div className="activity-icon" style={{ color: cfg.color }}>
                    <EventIcon size={13} />
                  </div>
                  <div className="activity-content">
                    <span className="activity-description">{item.description}</span>
                    {item.source && (
                      <span className="activity-source">{item.source}</span>
                    )}
                  </div>
                  <span className="activity-time">{formatTime(item.created_at)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default OverviewTab;
