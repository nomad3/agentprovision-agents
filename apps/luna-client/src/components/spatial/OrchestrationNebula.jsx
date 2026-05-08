/**
 * OrchestrationNebula — fills the spatial HUD's main canvas with the
 * tenant's living orchestrator state.
 *
 * Polls /api/v1/spatial/orchestration every 5s. Renders:
 *   - One sphere per active agent (color = status, intensity = busy)
 *   - One ring per active workflow, orbiting an agent if it has one
 *   - Pulsing edges for recent agent_audit_log entries (last 5 min)
 *
 * Lives alongside KnowledgeNebula (which renders memory entities) —
 * the two compose: knowledge dots in the background, agents+workflows
 * as the foreground "what's happening right now" layer.
 *
 * Added 2026-05-08 because the HUD looked like an empty void on tenants
 * with no live A2A coalition + no knowledge entities — even though the
 * tenant had agents and workflows running.
 */
import { useEffect, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

import { apiJson } from '../../api';

const POLL_INTERVAL_MS = 5000;

const STATUS_COLOR = {
  production: '#39d98a',  // green
  staging:    '#f4a83a',  // amber
  draft:      '#9ca3af',  // gray
  deprecated: '#6b7280',  // dim
};

function AgentSphere({ position, color, busy, error }) {
  const ref = useRef();
  useFrame(({ clock }) => {
    if (!ref.current) return;
    // Busy agents pulse; errored agents shake; idle ones drift.
    const t = clock.getElapsedTime();
    if (busy) {
      const s = 1 + Math.sin(t * 6) * 0.15;
      ref.current.scale.set(s, s, s);
    } else if (error) {
      ref.current.position.x = position[0] + Math.sin(t * 30) * 0.3;
    } else {
      ref.current.scale.set(1, 1, 1);
      ref.current.position.x = position[0];
    }
  });
  return (
    <mesh ref={ref} position={position}>
      <sphereGeometry args={[1.2, 24, 24]} />
      <meshStandardMaterial
        color={error ? '#e6584d' : color}
        emissive={error ? '#e6584d' : color}
        emissiveIntensity={busy ? 0.9 : error ? 0.7 : 0.25}
      />
    </mesh>
  );
}

function WorkflowRing({ centerPosition, radius, color, status }) {
  const ref = useRef();
  useFrame(({ clock }) => {
    if (!ref.current) return;
    // Active workflows spin; paused don't.
    if (status === 'active') {
      ref.current.rotation.z = clock.getElapsedTime() * 0.4;
    }
  });
  return (
    <mesh ref={ref} position={centerPosition}>
      <torusGeometry args={[radius, 0.08, 8, 48]} />
      <meshBasicMaterial color={color} transparent opacity={status === 'active' ? 0.7 : 0.25} />
    </mesh>
  );
}

function ActionPulse({ from, to, age }) {
  // Fade out over 2 seconds, then unmount externally.
  const opacity = Math.max(0, 1 - age / 2);
  return (
    <line>
      <bufferGeometry attach="geometry">
        <bufferAttribute
          attach="attributes-position"
          array={new Float32Array([...from, ...to])}
          count={2}
          itemSize={3}
        />
      </bufferGeometry>
      <lineBasicMaterial attach="material" color="#7d6cf2" transparent opacity={opacity * 0.8} />
    </line>
  );
}

function layoutAgents(agents) {
  // Place agents on a circle around the origin in the XZ plane.
  const radius = 12;
  return agents.map((a, i) => {
    const theta = (i / Math.max(agents.length, 1)) * Math.PI * 2;
    return {
      ...a,
      position: [Math.cos(theta) * radius, 0, Math.sin(theta) * radius],
    };
  });
}

export default function OrchestrationNebula({ tenantId }) {
  const [snapshot, setSnapshot] = useState({
    agents: [],
    workflows: [],
    recent_actions: [],
  });
  const [activePulses, setActivePulses] = useState([]);
  const seenActionKeys = useRef(new Set());

  // Poll the API.
  useEffect(() => {
    let cancelled = false;
    const fetch = async () => {
      try {
        const r = await apiJson('/api/v1/spatial/orchestration');
        if (!cancelled && r) setSnapshot(r);
      } catch (e) {
        // Silent — not authenticated, network hiccup, etc. The HUD
        // continues to render whatever was last fetched.
      }
    };
    fetch();
    const id = setInterval(fetch, POLL_INTERVAL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [tenantId]);

  const positionedAgents = layoutAgents(snapshot.agents);
  const agentById = Object.fromEntries(positionedAgents.map((a) => [a.id, a]));

  // Detect new actions and spawn pulses.
  useEffect(() => {
    const now = Date.now();
    const newPulses = [];
    for (const action of (snapshot.recent_actions || [])) {
      const key = `${action.agent_id}|${action.at}`;
      if (seenActionKeys.current.has(key)) continue;
      seenActionKeys.current.add(key);
      const agent = agentById[action.agent_id];
      if (!agent) continue;
      newPulses.push({
        key,
        from: agent.position,
        to: [0, 0, 0],
        spawnedAt: now,
      });
    }
    if (newPulses.length) {
      setActivePulses((prev) => [...prev.filter((p) => now - p.spawnedAt < 2000), ...newPulses]);
    }
    // Cleanup: drop pulses older than 2s on next tick.
    const cleanup = setInterval(() => {
      const t = Date.now();
      setActivePulses((prev) => prev.filter((p) => t - p.spawnedAt < 2000));
    }, 500);
    return () => clearInterval(cleanup);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshot]);

  return (
    <Canvas
      camera={{ position: [0, 18, 22], fov: 50 }}
      style={{ position: 'absolute', inset: 0, background: 'transparent' }}
    >
      <ambientLight intensity={0.4} />
      <pointLight position={[10, 20, 10]} intensity={0.8} />

      {positionedAgents.map((a) => (
        <AgentSphere
          key={a.id}
          position={a.position}
          color={STATUS_COLOR[a.status] || '#9ca3af'}
          busy={a.busy}
          error={a.error}
        />
      ))}

      {/* One workflow ring around each agent (round-robin assignment).
          With no agents → rings at origin so the user still sees motion. */}
      {snapshot.workflows.map((w, i) => {
        const agent = positionedAgents[i % Math.max(positionedAgents.length, 1)];
        return (
          <WorkflowRing
            key={w.id}
            centerPosition={agent ? agent.position : [0, 0, 0]}
            radius={2 + (i % 3) * 0.5}
            color={w.status === 'active' ? '#7d6cf2' : '#4b5563'}
            status={w.status}
          />
        );
      })}

      {activePulses.map((p) => (
        <ActionPulse
          key={p.key}
          from={p.from}
          to={p.to}
          age={(Date.now() - p.spawnedAt) / 1000}
        />
      ))}

      {/* Central "orchestrator" core sphere */}
      <mesh position={[0, 0, 0]}>
        <sphereGeometry args={[2, 32, 32]} />
        <meshStandardMaterial
          color="#60a5fa"
          emissive="#60a5fa"
          emissiveIntensity={0.3}
          wireframe
        />
      </mesh>
    </Canvas>
  );
}
