import { useMemo, useState } from 'react';

import CenterConversation from './CenterConversation';
import LeftRail from './LeftRail';
import RightPanel from './RightPanel';
import TerminalDrawer from './TerminalDrawer';
import TierPicker from './TierPicker';
import styles from './DenShell.module.css';
import { useTier } from './useTier';

/**
 * Alpha Control Plane Den shell — 3-zone grid + drawer.
 *
 * Same skeleton at every tier. Tier-aware density is applied via CSS
 * classes that adjust the grid column / row widths, plus per-zone
 * `capabilities.*` flags that hide non-applicable surfaces.
 *
 * Design: docs/plans/2026-05-15-alpha-control-plane-design.md §3
 */
export function DenShell({
  messages = [],
  onSend,
  disabled = false,
  context = null,
  streams = [],
}) {
  const [tier, , capabilities] = useTier();
  const [activeRail, setActiveRail] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const shellClass = useMemo(() => (
    `${styles.shell} ${styles[`shellTier${tier}`] || ''}`
  ), [tier]);

  // Tier 0: welcome card centerstage; no rail, no panel, no drawer.
  if (tier === 0) {
    return (
      <div className={styles.shell} data-testid="den-shell" data-tier={tier}>
        <button
          className={styles.tierPicker}
          onClick={() => setPickerOpen((v) => !v)}
          aria-label="Open tier picker"
          data-testid="open-tier-picker"
        >
          Tier {tier}
        </button>
        {pickerOpen && (
          <div style={{ position: 'absolute', top: 48, right: 12, padding: 16,
                        background: '#111', border: '1px solid #2a2a2a',
                        borderRadius: 8, zIndex: 20, maxWidth: 360 }}>
            <TierPicker onChange={() => setPickerOpen(false)} />
          </div>
        )}
        <div className={styles.center}>
          {messages.length === 0 ? (
            <div className={styles.welcomeCard} data-testid="welcome-card">
              <h2>Welcome to Alpha</h2>
              <p>
                Just chat. Ask alpha anything — about your data, your projects,
                or what it can do for you. When you're ready, open settings
                and bump your tier to unlock more of the den.
              </p>
              <button
                type="button"
                className={styles.previewToggle}
                onClick={() => setPickerOpen(true)}
                data-testid="show-what-this-can-become"
              >
                Show me what this can become →
              </button>
            </div>
          ) : null}
          <CenterConversation
            messages={messages}
            onSend={onSend}
            disabled={disabled}
            placeholder="Message alpha…"
          />
        </div>
      </div>
    );
  }

  // Tier 1+: full shell with tier-aware zone visibility.
  return (
    <div className={shellClass} data-testid="den-shell" data-tier={tier}>
      <button
        className={styles.tierPicker}
        onClick={() => setPickerOpen((v) => !v)}
        aria-label="Open tier picker"
        data-testid="open-tier-picker"
      >
        Tier {tier}
      </button>
      {pickerOpen && (
        <div style={{ position: 'absolute', top: 48, right: 12, padding: 16,
                      background: '#111', border: '1px solid #2a2a2a',
                      borderRadius: 8, zIndex: 20, maxWidth: 360 }}>
          <TierPicker onChange={() => setPickerOpen(false)} />
        </div>
      )}
      {capabilities.showRail ? (
        <LeftRail
          capabilities={capabilities}
          onSelect={setActiveRail}
          active={activeRail}
        />
      ) : (
        <div className={`${styles.rail} ${styles.railHidden}`} aria-hidden />
      )}
      <main className={styles.center}>
        <CenterConversation
          messages={messages}
          onSend={onSend}
          disabled={disabled}
        />
      </main>
      {capabilities.showRightPanel ? (
        <RightPanel context={context} />
      ) : (
        <div className={`${styles.right} ${styles.rightHidden}`} aria-hidden />
      )}
      <TerminalDrawer
        visible={capabilities.showDrawer}
        streams={streams}
      />
    </div>
  );
}

export default DenShell;
