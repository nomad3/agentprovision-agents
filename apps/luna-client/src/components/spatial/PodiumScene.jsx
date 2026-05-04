/**
 * PodiumScene — the wrapping Canvas + camera + post-processing for the Luna
 * OS conductor's podium. Composes:
 *   - Knowledge Nebula (existing) in the dim background
 *   - Podium (sections, agents, beams)
 *   - InboxMelody as an HTML overlay
 *   - Wake-state controlled scene fade (sleeping = dim/distant; armed = lit/close)
 *
 * The actual gesture engine + cursor + accessibility live in the existing
 * GestureProvider — this scene just consumes wake state and dispatches
 * point-and-voice events.
 */
import React, { useEffect, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { PerspectiveCamera, Stars } from '@react-three/drei';
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing';

import { useFleetSnapshot } from '../../hooks/useFleetSnapshot';
import { useFleetStream } from '../../hooks/useFleetStream';
import { useDispatchOnPoint } from '../../hooks/useDispatchOnPoint';
import { useGesture } from '../../hooks/useGesture';
import Podium from './Podium';
import Score from './Score';
import InboxMelody from './InboxMelody';
import VoiceDispatch from './VoiceDispatch';
import Movements from './Movements';
import { VoiceProvider } from '../../context/VoiceContext';

const EMPTY_SNAPSHOT = {
  agents: [],
  groups: [],
  active_collaborations: [],
  notifications: [],
  commitments: [],
  running_workflows: [],
  loaded: false,
  error: null,
};

function todayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

export default function PodiumScene() {
  const [snapshot, setSnapshot] = useState(EMPTY_SNAPSHOT);
  useFleetSnapshot(setSnapshot);
  useFleetStream(setSnapshot);
  useDispatchOnPoint();

  // Movements: morning overture (auto, once per day) + evening finale
  // (on-demand via window event `luna-finale`).
  const [movement, setMovement] = useState(null); // 'overture' | 'finale' | null
  useEffect(() => {
    const last = (() => {
      try { return localStorage.getItem('luna_overture_played'); } catch { return null; }
    })();
    if (last !== todayKey()) {
      setMovement('overture');
      try { localStorage.setItem('luna_overture_played', todayKey()); } catch {}
    }
    const showFinale = () => setMovement('finale');
    window.addEventListener('luna-finale', showFinale);
    return () => window.removeEventListener('luna-finale', showFinale);
  }, []);

  const { wakeState } = useGesture();
  const armed = wakeState === 'armed';

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: '#040816',
        overflow: 'hidden',
        // Whole-scene fade tied to wake state — sleeping = dimmer / further;
        // armed = bright. Smooth via CSS, no per-frame Three.js work.
        opacity: armed ? 1 : 0.62,
        transition: 'opacity 600ms ease-out',
      }}
    >
      <Canvas dpr={[1, 2]} gl={{ antialias: true, alpha: false }}>
        <PerspectiveCamera makeDefault position={[0, 1.6, 0]} fov={70} near={0.1} far={200} />

        {/* Background — a quiet starfield to give a sense of place. Phase
            B+ replaces this with the embedded Knowledge Nebula scene
            (requires extracting it from its self-owning Canvas). */}
        <Stars radius={120} depth={60} count={3500} factor={3} saturation={0.4} fade speed={0.4} />
        <fog attach="fog" args={['#040816', 12, 32]} />

        <Podium snapshot={snapshot} armed={armed} />
        <Score runs={snapshot.running_workflows || []} />

        <EffectComposer>
          <Bloom luminanceThreshold={0.25} luminanceSmoothing={0.6} intensity={0.9} mipmapBlur />
          <Vignette eskil={false} offset={0.18} darkness={0.85} />
        </EffectComposer>
      </Canvas>

      <VoiceProvider>
        <VoiceDispatch />
      </VoiceProvider>

      {/* Finale trigger — manual review of the day's performance. Pairs
          with the auto-firing morning overture. */}
      <button
        onClick={() => window.dispatchEvent(new Event('luna-finale'))}
        style={{
          position: 'absolute',
          bottom: 16,
          right: 88,
          padding: '6px 14px',
          borderRadius: 18,
          border: '1px solid #4cf',
          background: 'rgba(20,40,80,0.5)',
          color: '#cce',
          cursor: 'pointer',
          fontFamily: 'ui-sans-serif',
          fontSize: 13,
          zIndex: 12,
        }}
        title="Review the day's performance"
      >
        Finale
      </button>

      <InboxMelody
        notifications={snapshot.notifications || []}
        commitments={snapshot.commitments || []}
      />

      {/* Wake-state badge — small, bottom-left, always visible */}
      <div
        style={{
          position: 'absolute',
          bottom: 16,
          left: 16,
          padding: '4px 10px',
          borderRadius: 4,
          background: armed ? 'rgba(76,255,255,0.18)' : 'rgba(120,120,140,0.18)',
          border: `1px solid ${armed ? '#4cf' : '#445'}`,
          color: armed ? '#4cf' : '#9ad',
          fontFamily: 'ui-monospace, Menlo, monospace',
          fontSize: 11,
          pointerEvents: 'none',
          zIndex: 10,
        }}
      >
        {wakeState.toUpperCase()}
      </div>

      {/* Movements — morning overture / evening finale overlay */}
      {movement && (
        <Movements kind={movement} onDone={() => setMovement(null)} />
      )}

      {/* Loading skeleton for first-paint */}
      {!snapshot.loaded && (
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            color: '#9ad',
            fontFamily: 'ui-monospace, Menlo, monospace',
            fontSize: 14,
          }}
        >
          Tuning the orchestra…
        </div>
      )}
    </div>
  );
}
