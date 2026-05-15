import styles from './DenShell.module.css';

/**
 * Bottom terminal drawer.
 *
 * Tier 0–3 scope: hidden. Tier 4+ surfaces the live cli_subprocess_stream
 * events as a multi-tab terminal. The streaming component itself is a
 * separate spec (see design §6.1).
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md §3 → "Bottom drawer"
 */
export function TerminalDrawer({ visible, streams }) {
  if (!visible) return null;
  return (
    <div className={styles.drawer} role="region" aria-label="Live terminal">
      {(streams || []).length === 0 ? (
        <div>
          $ alpha — no active subprocess streams. Run something that
          spawns a CLI to see live output here.
        </div>
      ) : (
        streams.map((s, i) => (
          // Prefer stable identifiers; index fallback is permissive.
          <pre key={s.event_id || s.seq_no || `idx-${i}`} style={{ margin: 0 }}>
            {s.chunk}
          </pre>
        ))
      )}
    </div>
  );
}

export default TerminalDrawer;
