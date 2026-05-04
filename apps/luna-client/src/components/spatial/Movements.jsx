/**
 * Movements — the morning overture and evening finale of Luna OS. Both
 * surfaces share a single timeline-driven HTML overlay that fades through
 * a sequence of "panels" summarizing recent activity. The conductor can
 * dismiss with the gesture-bound `dismiss` action (fist) or by clicking.
 *
 * Overture: triggered automatically once per day on the user's first
 * podium visit. Stores the last-played date in localStorage.
 *
 * Finale: triggered explicitly via the `nav_finale` gesture binding (or a
 * tray menu later) — same data, different framing copy.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useBriefing } from '../../hooks/useBriefing';

const PANEL_DURATION_MS = 2400;

function buildPanels(briefing, kind) {
  if (!briefing) return [];
  const t = briefing.totals || {};
  const panels = [];
  panels.push({
    id: 'open',
    headline: kind === 'overture' ? 'Good morning, conductor.' : 'Performance review.',
    subtitle:
      kind === 'overture'
        ? 'Here is what the orchestra played overnight.'
        : 'Here is what the orchestra played today.',
  });
  if (t.workflows_completed || t.workflows_failed) {
    panels.push({
      id: 'workflows',
      headline: `${t.workflows_completed || 0} workflows completed`,
      subtitle:
        t.workflows_failed > 0
          ? `${t.workflows_failed} needed a retake.`
          : 'No retakes needed.',
    });
  }
  if (t.memory_activities) {
    panels.push({
      id: 'memory',
      headline: `${t.memory_activities} new memories`,
      subtitle: 'Learnings the orchestra committed to the score.',
    });
  }
  if (t.notifications_received) {
    panels.push({
      id: 'notifs',
      headline: `${t.notifications_received} new arrivals`,
      subtitle: 'Inbox items waiting for your downbeat.',
    });
  }
  if (t.open_commitments) {
    panels.push({
      id: 'commitments',
      headline: `${t.open_commitments} open commitments`,
      subtitle: 'Promises the orchestra still owes.',
    });
  }
  panels.push({
    id: 'close',
    headline: kind === 'overture' ? 'You may begin.' : 'Encore.',
    subtitle: 'Raise your palm to take the podium.',
  });
  return panels;
}

export default function Movements({ kind, onDone }) {
  // kind: 'overture' | 'finale'
  const { briefing, fetchBriefing } = useBriefing();
  const [panelIdx, setPanelIdx] = useState(0);
  const timerRef = useRef(null);

  useEffect(() => {
    fetchBriefing();
  }, [fetchBriefing]);

  const panels = useMemo(() => buildPanels(briefing, kind), [briefing, kind]);

  useEffect(() => {
    if (!panels.length) return;
    if (panelIdx >= panels.length) {
      onDone?.();
      return;
    }
    timerRef.current = setTimeout(
      () => setPanelIdx((i) => i + 1),
      PANEL_DURATION_MS,
    );
    return () => clearTimeout(timerRef.current);
  }, [panelIdx, panels, onDone]);

  // Listen for the dismiss action (fist gesture or click).
  useEffect(() => {
    const handler = () => onDone?.();
    window.addEventListener('luna-dismiss', handler);
    return () => window.removeEventListener('luna-dismiss', handler);
  }, [onDone]);

  if (!panels.length) return null;
  const current = panels[Math.min(panelIdx, panels.length - 1)];

  return (
    <div
      onClick={() => onDone?.()}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'radial-gradient(ellipse at center, rgba(12,18,40,0.92), rgba(2,4,16,0.97))',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        color: '#cce',
        fontFamily: 'ui-sans-serif, system-ui, sans-serif',
        zIndex: 50,
        cursor: 'pointer',
        animation: 'lunaMovementsFade 0.6s ease-out',
      }}
      aria-label={kind}
    >
      <div
        key={current.id}
        style={{
          fontSize: 38,
          fontWeight: 600,
          color: '#cfd8ff',
          textShadow: '0 0 24px rgba(120,160,255,0.35)',
          textAlign: 'center',
          maxWidth: '70vw',
          animation: 'lunaPanelIn 0.7s ease-out',
        }}
      >
        {current.headline}
      </div>
      <div
        style={{
          marginTop: 12,
          fontSize: 18,
          color: '#9ad',
          textAlign: 'center',
          maxWidth: '60vw',
          opacity: 0.85,
        }}
      >
        {current.subtitle}
      </div>
      <div
        style={{
          position: 'absolute',
          bottom: 32,
          fontSize: 12,
          color: '#678',
          fontFamily: 'ui-monospace, Menlo, monospace',
        }}
      >
        {kind === 'overture' ? 'OVERTURE' : 'FINALE'} · click or fist to dismiss · {panelIdx + 1}/{panels.length}
      </div>
      <style>{`
        @keyframes lunaMovementsFade {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes lunaPanelIn {
          from { opacity: 0; transform: translateY(12px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
