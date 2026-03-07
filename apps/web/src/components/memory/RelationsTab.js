import React, { useEffect, useState } from 'react';
import { Spinner } from 'react-bootstrap';
import { FaArrowRight, FaProjectDiagram, FaTrash } from 'react-icons/fa';
import { getCategoryConfig, RELATION_TYPES } from './constants';
import { memoryService } from '../../services/memory';

const PAGE_SIZE = 50;

const RelationsTab = () => {
  const [relations, setRelations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState('');
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    loadRelations(true);
  }, [typeFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadRelations = async (reset = true) => {
    try {
      setLoading(true);
      const skip = reset ? 0 : offset;
      const data = await memoryService.getAllRelations({
        relationType: typeFilter || undefined,
        skip,
        limit: PAGE_SIZE,
      });
      const items = data || [];
      if (reset) {
        setRelations(items);
        setOffset(items.length);
      } else {
        setRelations(prev => [...prev, ...items]);
        setOffset(prev => prev + items.length);
      }
      setHasMore(items.length === PAGE_SIZE);
    } catch (err) {
      console.error('Failed to load relations:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await memoryService.deleteRelation(id);
      setRelations(prev => prev.filter(r => r.id !== id));
    } catch (err) {
      console.error('Failed to delete relation:', err);
    }
  };

  // Group by relation type
  const grouped = {};
  relations.forEach(rel => {
    const type = rel.relation_type || 'related_to';
    if (!grouped[type]) grouped[type] = [];
    grouped[type].push(rel);
  });

  const sortedTypes = Object.keys(grouped).sort((a, b) => grouped[b].length - grouped[a].length);

  return (
    <div className="relations-tab">
      <div className="relations-tab-header">
        <p className="relations-tab-subtitle">
          Connections between entities in Luna's knowledge graph
        </p>
        <select
          className="filter-select"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          <option value="">All Types</option>
          {RELATION_TYPES.map(t => (
            <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </div>

      {loading && relations.length === 0 ? (
        <div className="text-center py-5">
          <Spinner animation="border" size="sm" className="text-muted" />
        </div>
      ) : relations.length === 0 ? (
        <div className="memory-empty">
          <div className="memory-empty-icon"><FaProjectDiagram /></div>
          <p>No relations yet. Luna discovers connections between entities as she learns from your conversations.</p>
        </div>
      ) : (
        <>
          {sortedTypes.map(type => (
            <div key={type} className="relation-type-group">
              <div className="relation-type-header">
                <FaProjectDiagram size={13} style={{ color: '#a78bfa' }} />
                <span className="relation-type-label">{type.replace(/_/g, ' ')}</span>
                <span className="relation-type-count">{grouped[type].length}</span>
              </div>
              <div className="relation-type-cards">
                {grouped[type].map(rel => {
                  const fromCfg = getCategoryConfig(rel.from_entity_category);
                  const toCfg = getCategoryConfig(rel.to_entity_category);
                  const FromIcon = fromCfg.icon;
                  const ToIcon = toCfg.icon;

                  return (
                    <div key={rel.id} className="relation-card">
                      <div className="relation-card-entities">
                        <div className="relation-card-entity">
                          <span className="relation-entity-icon" style={{ background: fromCfg.bg, color: fromCfg.color }}>
                            <FromIcon size={11} />
                          </span>
                          <span className="relation-entity-name">{rel.from_entity_name || 'Unknown'}</span>
                          {rel.from_entity_category && (
                            <span className="relation-entity-cat" style={{ color: fromCfg.color }}>{rel.from_entity_category}</span>
                          )}
                        </div>
                        <div className="relation-card-arrow">
                          <FaArrowRight size={10} style={{ color: '#a78bfa' }} />
                          <span className="relation-card-type">{rel.relation_type.replace(/_/g, ' ')}</span>
                        </div>
                        <div className="relation-card-entity">
                          <span className="relation-entity-icon" style={{ background: toCfg.bg, color: toCfg.color }}>
                            <ToIcon size={11} />
                          </span>
                          <span className="relation-entity-name">{rel.to_entity_name || 'Unknown'}</span>
                          {rel.to_entity_category && (
                            <span className="relation-entity-cat" style={{ color: toCfg.color }}>{rel.to_entity_category}</span>
                          )}
                        </div>
                      </div>
                      <div className="relation-card-meta">
                        <div className="relation-strength-bar">
                          <div
                            className="relation-strength-fill"
                            style={{ width: `${(rel.strength || 1) * 100}%` }}
                          />
                        </div>
                        <span className="relation-card-date">
                          {new Date(rel.created_at).toLocaleDateString()}
                        </span>
                        <button
                          className="relation-card-delete"
                          onClick={() => handleDelete(rel.id)}
                          title="Delete relation"
                        >
                          <FaTrash size={10} />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}

          {hasMore && (
            <div className="memory-load-more">
              <button
                className="btn btn-outline-secondary btn-sm"
                onClick={() => loadRelations(false)}
                disabled={loading}
              >
                {loading ? <Spinner size="sm" animation="border" /> : 'Load More'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default RelationsTab;
