/*
 * CommandPalette — ⌘K / Ctrl+K universal jump.
 *
 * Brand-styled modal overlay. Unified search across:
 *   - Chat sessions  (opens the session in the dashboard chat)
 *   - Agents         (navigates to /agents/:id)
 *   - Static nav     (Memory, Skills, Workflows, Integrations, Settings)
 *
 * Keyboard:
 *   ⌘K / Ctrl+K  open
 *   Esc          close
 *   ↑ ↓          move highlight
 *   Enter        execute highlighted result
 *
 * Phase 2 v1 keeps the data sources to two existing services (chat,
 * agents) + a fixed nav table. Memory/skill/workflow live-fetch lands
 * alongside the live sidebar panels in a follow-up.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Modal } from 'react-bootstrap';
import { useNavigate } from 'react-router-dom';
import {
  FaComments, FaRobot, FaDatabase, FaPuzzlePiece,
  FaProjectDiagram, FaPlug, FaCog, FaSearch,
} from 'react-icons/fa';
import './CommandPalette.css';

const STATIC_NAV = [
  { kind: 'nav', id: 'nav:memory', label: 'Memory', sub: 'Knowledge graph + episodes', Icon: FaDatabase, to: '/memory' },
  { kind: 'nav', id: 'nav:skills', label: 'Skills', sub: 'Skill library', Icon: FaPuzzlePiece, to: '/skills' },
  { kind: 'nav', id: 'nav:workflows', label: 'Workflows', sub: 'Automation + execution', Icon: FaProjectDiagram, to: '/workflows' },
  { kind: 'nav', id: 'nav:integrations', label: 'Integrations', sub: 'Connectors + data sources', Icon: FaPlug, to: '/integrations' },
  { kind: 'nav', id: 'nav:settings', label: 'Settings', sub: 'Profile + platform', Icon: FaCog, to: '/settings' },
];

const _normalize = (s) => (s || '').toLowerCase();

const CommandPalette = ({ open, onClose, sessions = [], agents = [], onSelectSession }) => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  // Reset state when opening
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setHighlight(0);
    // Focus input on next tick (after Modal animation)
    const t = setTimeout(() => inputRef.current?.focus(), 30);
    return () => clearTimeout(t);
  }, [open]);

  const results = useMemo(() => {
    const items = [
      ...sessions.map((s) => ({
        kind: 'session',
        id: `session:${s.id}`,
        label: s.title || 'Untitled chat',
        sub: s.message_count != null ? `${s.message_count} messages` : 'Chat session',
        Icon: FaComments,
        session: s,
      })),
      ...agents.map((a) => ({
        kind: 'agent',
        id: `agent:${a.id}`,
        label: a.name || 'Unnamed agent',
        sub: a.role || 'Agent',
        Icon: FaRobot,
        to: `/agents/${a.id}`,
      })),
      ...STATIC_NAV,
    ];
    const q = _normalize(query);
    if (!q) return items.slice(0, 50);
    return items.filter((it) =>
      _normalize(it.label).includes(q) || _normalize(it.sub).includes(q)
    ).slice(0, 50);
  }, [query, sessions, agents]);

  // Clamp highlight when results change.
  useEffect(() => {
    if (highlight >= results.length) setHighlight(Math.max(0, results.length - 1));
  }, [results, highlight]);

  const execute = useCallback((item) => {
    if (!item) return;
    onClose();
    if (item.kind === 'session') {
      onSelectSession?.(item.session);
    } else if (item.to) {
      navigate(item.to);
    }
  }, [navigate, onClose, onSelectSession]);

  const handleKey = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      execute(results[highlight]);
    }
  };

  // Scroll highlighted into view.
  useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current.querySelector(`[data-idx="${highlight}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [highlight]);

  return (
    <Modal show={open} onHide={onClose} centered className="cmd-palette-modal" backdropClassName="cmd-palette-backdrop">
      <div className="cmd-palette">
        <div className="cmd-palette-input-row">
          <FaSearch size={12} className="cmd-palette-input-icon" />
          <input
            ref={inputRef}
            type="text"
            className="cmd-palette-input"
            placeholder="Search sessions, agents, or jump to a page…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKey}
            aria-label="Command palette search"
          />
          <kbd className="cmd-palette-kbd">Esc</kbd>
        </div>
        <ul className="cmd-palette-results" ref={listRef} role="listbox">
          {results.length === 0 ? (
            <li className="cmd-palette-empty">No matches.</li>
          ) : (
            results.map((it, idx) => {
              const Icon = it.Icon;
              return (
                <li
                  key={it.id}
                  data-idx={idx}
                  role="option"
                  aria-selected={idx === highlight}
                  className={`cmd-palette-row${idx === highlight ? ' active' : ''}`}
                  onMouseEnter={() => setHighlight(idx)}
                  onClick={() => execute(it)}
                >
                  <Icon size={14} className="cmd-palette-row-icon" />
                  <div className="cmd-palette-row-body">
                    <div className="cmd-palette-row-label">{it.label}</div>
                    <div className="cmd-palette-row-sub">{it.sub}</div>
                  </div>
                  <span className="cmd-palette-row-kind">{it.kind}</span>
                </li>
              );
            })
          )}
        </ul>
        <div className="cmd-palette-footer">
          <span><kbd>↑↓</kbd> navigate</span>
          <span><kbd>Enter</kbd> open</span>
          <span><kbd>Esc</kbd> close</span>
        </div>
      </div>
    </Modal>
  );
};

export default CommandPalette;
