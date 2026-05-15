import styles from './DenShell.module.css';

/**
 * Right context panel.
 *
 * Tier 0–1 scope: placeholder shell only. The polymorphic context
 * library (file diffs, memory entries, lead cards, etc.) lands in
 * Tier 2+ as a separate spec (see design §6.3).
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md §3 → "Right panel"
 */
export function RightPanel({ context }) {
  return (
    <aside className={styles.right} aria-label="Context panel">
      {context ? (
        <pre style={{ padding: 16, fontSize: 12 }}>
          {JSON.stringify(context, null, 2)}
        </pre>
      ) : (
        <div style={{ padding: 16, color: '#6b6b6b' }}>
          No context active. Alpha will surface tool calls, file diffs,
          and memory hits here as it works.
        </div>
      )}
    </aside>
  );
}

export default RightPanel;
