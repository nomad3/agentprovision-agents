import React, { useState } from 'react';
import { Button, Form, Spinner } from 'react-bootstrap';
import { FaEdit, FaSave, FaTrash } from 'react-icons/fa';
import { getMemoryTypeConfig } from './constants';

const MemoryCard = ({ memory, onUpdate, onDelete }) => {
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(memory.content);
  const [saving, setSaving] = useState(false);

  const cfg = getMemoryTypeConfig(memory.memory_type);
  const Icon = cfg.icon;

  const handleSave = async () => {
    if (!content.trim()) return;
    setSaving(true);
    try {
      await onUpdate(memory.id, { content: content.trim() });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '';
    return new Date(dateStr).toLocaleDateString(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
    });
  };

  return (
    <div className="memory-card">
      <div className="memory-card-icon" style={{ background: cfg.bg, color: cfg.color }}>
        <Icon size={14} />
      </div>
      <div className="memory-card-body">
        {editing ? (
          <div className="memory-card-edit">
            <Form.Control
              as="textarea"
              rows={2}
              size="sm"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="entity-input mb-2"
              autoFocus
            />
            <div className="d-flex gap-2">
              <Button variant="link" size="sm" className="p-0 text-muted" onClick={() => { setEditing(false); setContent(memory.content); }}>
                Cancel
              </Button>
              <Button variant="link" size="sm" className="p-0 text-primary" onClick={handleSave} disabled={saving}>
                {saving ? <Spinner size="sm" animation="border" /> : <><FaSave size={11} className="me-1" />Save</>}
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="memory-card-content">{memory.content}</div>
            <div className="memory-card-meta">
              {memory.source && <span className="memory-card-source">{memory.source}</span>}
              <span className="memory-card-date">{formatDate(memory.created_at)}</span>
              {memory.importance != null && (
                <span className="memory-card-importance">
                  {(memory.importance * 100).toFixed(0)}% importance
                </span>
              )}
            </div>
          </>
        )}
      </div>
      {!editing && (
        <div className="memory-card-actions">
          <button className="memory-action-btn" onClick={() => setEditing(true)} title="Edit">
            <FaEdit size={12} />
          </button>
          <button className="memory-action-btn delete" onClick={() => onDelete(memory.id)} title="Delete">
            <FaTrash size={11} />
          </button>
        </div>
      )}
    </div>
  );
};

export default MemoryCard;
