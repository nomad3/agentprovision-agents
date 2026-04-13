import React, { useEffect, useState, useRef } from 'react';
import KnowledgeNebula from './KnowledgeNebula';
import { apiJson } from '../../api';
import './SpatialHUD.css';

export default function SpatialHUD() {
  const [stats, setStats] = useState({ tokens: 65, cost: 0.42, manaPercent: 65 });
  const [activeQuests, setActiveQuests] = useState([]);
  const [commsLog, setCommsLog] = useState([]);
  const [trackingActive, setTrackingActive] = useState(false);
  const [nodes, setNodes] = useState([]);
  const [consensus, setConsensus] = useState(0);
  const lastFrameRef = useRef(0);
  
  useEffect(() => {
    // 1. Fetch real embeddings and project them via Rust
    (async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const data = await apiJson('/api/v1/memories/search/internal?query=all&limit=100');
        if (data && data.results) {
          const vectors = data.results.map(r => r.embedding).filter(Boolean);
          const ids = data.results.map(r => r.id);
          if (vectors.length > 2) {
            const projections = await invoke('project_embeddings', { vectors, ids });
            const projectedNodes = projections.map(p => {
              const original = data.results.find(r => r.id === p.id);
              return {
                id: p.id,
                position: [p.x, p.y, p.z],
                name: original.text_content?.substring(0, 30) || 'Unknown',
                type: original.content_type || 'memory',
              };
            });
            setNodes(projectedNodes);
          }
        }
      } catch (e) {
        console.warn('Nebula population failed:', e);
      }
    })();

    // 2. Start native spatial capture
    let unlistenFrame;
    (async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const { listen } = await import('@tauri-apps/api/event');
        await invoke('start_spatial_capture');
        unlistenFrame = await listen('spatial-frame', (event) => {
          setTrackingActive(true);
          lastFrameRef.current = Date.now();
        });
      } catch (e) {
        console.warn('Spatial tracking not available:', e);
      }
    })();

    // 3. Listen for Live Collaboration Events (Raid Status)
    let eventUnlisten;
    (async () => {
      try {
        const { listen } = await import('@tauri-apps/api/event');
        eventUnlisten = await listen('collaboration-event', (event) => {
          const { event_type, payload } = event.payload;
          switch(event_type) {
            case 'collaboration_started':
              setActiveQuests(prev => [...prev, {
                id: payload.collaboration_id,
                title: `RAID: ${payload.pattern.toUpperCase()}`,
                phase: 'INITIALIZING',
                progress: 0
              }]);
              break;
            case 'phase_started':
              setActiveQuests(prev => prev.map(q => 
                q.id === payload.collaboration_id 
                  ? { ...q, phase: payload.phase.toUpperCase(), progress: Math.min(q.progress + 20, 90) } 
                  : q
              ));
              break;
            case 'blackboard_entry':
              setCommsLog(prev => [{
                time: new Date().toLocaleTimeString(),
                agent: payload.author_slug,
                text: payload.content_preview,
                active: true
              }, ...prev].slice(0, 50));
              setConsensus(prev => Math.min(prev + 5, 95));
              break;
            case 'collaboration_completed':
              setConsensus(100);
              setActiveQuests(prev => prev.map(q => 
                q.id === payload.collaboration_id 
                  ? { ...q, phase: 'COMPLETED', progress: 100 } 
                  : q
              ));
              break;
          }
        });
      } catch (e) {
        console.warn('Event listener failed:', e);
      }
    })();

    const interval = setInterval(() => {
      if (Date.now() - lastFrameRef.current > 1000) setTrackingActive(false);
    }, 1000);

    // Keyboard controller
    const handleKeyDown = (e) => {
      switch(e.code) {
        case 'KeyW': case 'KeyA': case 'KeyS': case 'KeyD':
          break; // Handled in NebulaCamera
        case 'Digit1': case 'Digit2': case 'Digit3': case 'Digit4':
          console.log('Switch Agent Party member:', e.code.replace('Digit', ''));
          break;
        default: break;
      }
    };
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      unlistenFrame?.();
      eventUnlisten?.();
      clearInterval(interval);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  return (
    <div className="spatial-hud-container">
      <KnowledgeNebula nodes={nodes} />

      <header className="hud-top">
        <div className="hud-group">
          <div className="hud-stat">
            <label>SPATIAL SYNC</label>
            <div className={`sync-indicator ${trackingActive ? 'active' : 'searching'}`}>
              {trackingActive ? 'LOCKED' : 'SEARCHING...'}
            </div>
          </div>
          <div className="hud-stat">
            <label>MANA (TOKENS)</label>
            <div className="hud-bar-container">
              <div className="hud-bar-fill" style={{width: `${stats.manaPercent}%`}}></div>
            </div>
          </div>
          <div className="hud-stat">
            <label>PARTY HEAT</label>
            <span className="hud-value">${stats.cost.toFixed(2)} <small>USD</small></span>
          </div>
        </div>

        <div className="hud-party">
          <div className="party-member active">
            <div className="member-status">THINKING</div>
            <div className="member-name">Triage</div>
          </div>
          <div className="party-member">
            <div className="member-status">READY</div>
            <div className="member-name">Data-Inv</div>
          </div>
          <div className="party-member locked">
            <div className="member-status">LOCKED</div>
            <div className="member-name">Analyst</div>
          </div>
          <div className="party-member locked">
            <div className="member-status">LOCKED</div>
            <div className="member-name">Commander</div>
          </div>
        </div>
      </header>

      <aside className="hud-left">
        <div className="hud-module-label">ACTIVE MISSIONS</div>
        {activeQuests.length === 0 && <div className="no-quests" style={{color: 'rgba(100,180,255,0.4)', padding: '10px'}}>NO ACTIVE RAIDS</div>}
        {activeQuests.map(quest => (
          <div key={quest.id} className="quest-card">
            <div className="quest-title">{quest.title}</div>
            <div className="quest-progress-info">
              <span>PHASE: {quest.phase}</span>
              <span>{quest.progress}%</span>
            </div>
            <div className="quest-progress-bar">
              <div className="quest-progress-fill" style={{width: `${quest.progress}%`}}></div>
            </div>
          </div>
        ))}
      </aside>

      <footer className="hud-bottom">
        <div className="hud-module-label">A2A COMBAT LOG</div>
        <div className="comms-terminal">
          {commsLog.length === 0 && <div className="comms-placeholder" style={{opacity: 0.3, fontSize: '10px'}}>WAITING FOR PARTY COMMS...</div>}
          {commsLog.map((log, i) => (
            <div key={i} className={`comms-line ${log.active ? 'active' : ''}`}>
              <span className="time">{log.time}</span> <span className="agent">{log.agent}</span>: {log.text}
            </div>
          ))}
          <div className="cursor-blink">_</div>
        </div>
      </footer>

      <div className="consensus-meter">
        <div className="meter-label">COALITION CONSENSUS</div>
        <div className="meter-container">
          <div className="meter-fill" style={{width: `${consensus}%`}}></div>
        </div>
      </div>

      <div className="hud-crosshair">
        <div className="ch-top"></div>
        <div className="ch-bottom"></div>
        <div className="ch-left"></div>
        <div className="ch-right"></div>
      </div>
    </div>
  );
}
