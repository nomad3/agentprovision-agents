/**
 * The Score — running workflows visualized as flowing graphs across the
 * floor of the Luna OS spatial scene. Each running workflow is a small
 * directed chain of step nodes; status drives color (running=cyan,
 * completed=green, error=red, pending=gray); active step pulses.
 *
 * Layout: workflows tile along the floor in front of the conductor, below
 * the section ring. Each workflow occupies a horizontal strip; steps lay
 * left-to-right within it. New strips push older ones further from the
 * podium so recency is "closer."
 */
import React, { useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Text } from '@react-three/drei';

const STATUS_COLOR = {
  running: '#4cf',
  completed: '#7d7',
  failed: '#f66',
  error: '#f66',
  pending: '#666',
  skipped: '#aaa',
};

function StepNode({ step, position, isCurrent }) {
  const ref = React.useRef();
  const color = STATUS_COLOR[step.status] || '#888';

  useFrame((state) => {
    if (!ref.current) return;
    if (step.status === 'running' || isCurrent) {
      const t = state.clock.elapsedTime;
      ref.current.material.emissiveIntensity = 0.7 + Math.sin(t * 4) * 0.3;
    } else {
      ref.current.material.emissiveIntensity = 0.4;
    }
  });

  return (
    <mesh ref={ref} position={position}>
      <boxGeometry args={[0.55, 0.18, 0.22]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.4} />
    </mesh>
  );
}

function StepLink({ from, to, color = '#4cf', running }) {
  const ref = React.useRef();
  useFrame((state) => {
    if (!ref.current) return;
    const t = state.clock.elapsedTime;
    ref.current.material.opacity = running ? 0.55 + Math.sin(t * 5) * 0.2 : 0.35;
  });
  // Simple straight line as a thin box
  const dx = to[0] - from[0];
  const length = Math.abs(dx);
  const mid = [(from[0] + to[0]) / 2, from[1], from[2]];
  return (
    <mesh ref={ref} position={mid}>
      <boxGeometry args={[length, 0.04, 0.04]} />
      <meshBasicMaterial color={color} transparent opacity={0.4} depthWrite={false} />
    </mesh>
  );
}

function WorkflowStrip({ run, stripIndex, totalStrips }) {
  // Position strips fanning out in front of the conductor along z.
  // stripIndex 0 = closest, larger = further.
  const z = -3.5 - stripIndex * 0.85;
  const xOffset = -((run.steps.length - 1) * 0.7) / 2;

  const stepPositions = useMemo(() => {
    const n = Math.max(1, run.steps.length);
    return run.steps.map((_, i) => [xOffset + i * 0.7, -0.1, z]);
  }, [run.steps.length, xOffset, z]);

  const labelPos = [stepPositions[0]?.[0] - 0.6 || -3, -0.05, z];
  const isRunning = run.status === 'running';

  return (
    <group>
      <Text
        position={labelPos}
        fontSize={0.13}
        color={STATUS_COLOR[run.status] || '#cce'}
        anchorX="right"
        anchorY="middle"
        outlineWidth={0.005}
        outlineColor="#000"
      >
        {(run.workflow_name || 'workflow').slice(0, 24)}
      </Text>
      {run.steps.map((s, i) => (
        <StepNode
          key={s.id || `${run.id}-${i}`}
          step={s}
          position={stepPositions[i]}
          isCurrent={s.step_id === run.current_step}
        />
      ))}
      {run.steps.slice(0, -1).map((_, i) => (
        <StepLink
          key={`link-${run.id}-${i}`}
          from={stepPositions[i]}
          to={stepPositions[i + 1]}
          running={isRunning}
        />
      ))}
    </group>
  );
}

export default function Score({ runs = [] }) {
  if (!runs.length) return null;
  // Cap at 8 strips so the floor doesn't get crowded.
  const strips = runs.slice(0, 8);
  return (
    <group>
      {strips.map((r, i) => (
        <WorkflowStrip key={r.id} run={r} stripIndex={i} totalStrips={strips.length} />
      ))}
    </group>
  );
}
