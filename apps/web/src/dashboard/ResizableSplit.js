/*
 * ResizableSplit — VSCode-style draggable column layout.
 *
 * Wraps N children in a CSS Grid with N-1 vertical drag handles
 * between them. Mouse-drag a handle to grow one pane while shrinking
 * its neighbour. Double-click a handle to reset to defaultSizes.
 *
 * Sizes are stored as percentages summing to 100 and persisted to
 * localStorage under `storageKey`. `minSizes` is a px floor per pane
 * (enforced during drag, in viewport-pixels). Below 992 px viewport
 * the component degrades to a vertical flex stack with no handles;
 * passing `disabled` does the same regardless of viewport.
 *
 * Pure vanilla — no `react-resizable-panels` or other deps.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './ResizableSplit.css';

const MOBILE_BREAKPOINT = 992;

// Largest editor-group count we ever persist sizes for. Used by the
// one-time GC sweep below to scrub stale `${storageKey}.${oldN}` keys
// (e.g. user splits to 3 panes, persists `…sizes.3`, then closes a
// split — the `…sizes.3` entry would otherwise leak forever).
const MAX_EDITOR_GROUPS_GC = 8;

const sanitiseSizes = (sizes, count) => {
  if (!Array.isArray(sizes) || sizes.length !== count) return null;
  if (!sizes.every((n) => typeof n === 'number' && Number.isFinite(n) && n > 0)) return null;
  const sum = sizes.reduce((a, b) => a + b, 0);
  if (sum <= 0) return null;
  // Normalise to exactly 100.
  return sizes.map((n) => (n / sum) * 100);
};

// Re-clamp loaded percentages against the current container width:
// any pane whose computed px size sits below its `minSizes[i]` floor
// is raised to that floor; the surplus is taken proportionally from
// the other panes; the result is renormalised to sum 100. Without
// this, a layout persisted on a wide monitor (e.g. 18% sessions pane
// = 280px) collapses to <160px when loaded on a laptop and the pane
// becomes unusable on first paint — the mousemove clamp only fires
// during a drag, never at hydration.
const clampPercentagesToMinPixels = (sizes, mins, containerWidth) => {
  if (!Array.isArray(sizes) || sizes.length === 0) return sizes;
  if (!containerWidth || containerWidth <= 0) return sizes;
  if (!Array.isArray(mins) || mins.length !== sizes.length) return sizes;

  const minPcts = mins.map((m) => Math.max(0, (m / containerWidth) * 100));
  const totalMin = minPcts.reduce((a, b) => a + b, 0);
  // If the floors alone exceed 100% the container is genuinely too
  // narrow — fall back to a proportional layout of the floors so the
  // grid still renders something rather than NaN/negative tracks.
  if (totalMin >= 100) {
    return minPcts.map((p) => (p / totalMin) * 100);
  }
  // Lift any pane below its floor; track surplus we need to reclaim
  // from the panes that *are* above their floor.
  const lifted = sizes.map((p, i) => (p < minPcts[i] ? minPcts[i] : p));
  const sum = lifted.reduce((a, b) => a + b, 0);
  if (Math.abs(sum - 100) < 0.01) return lifted;

  // Renormalise: scale the headroom (above-floor portion) of each
  // pane so the total comes back to 100. Panes pinned at the floor
  // stay pinned.
  const headroom = lifted.map((p, i) => Math.max(0, p - minPcts[i]));
  const totalHeadroom = headroom.reduce((a, b) => a + b, 0);
  const target = 100 - minPcts.reduce((a, b) => a + b, 0);
  if (totalHeadroom <= 0 || target <= 0) {
    // Every pane is at its floor — just renormalise the floors.
    return lifted.map((p) => (p / sum) * 100);
  }
  return lifted.map((p, i) => minPcts[i] + (headroom[i] / totalHeadroom) * target);
};

// One-time GC for stale `${baseKey}.${N}` entries. We only sweep keys
// shaped like our editor-groups pattern (`dcc.editorGroups.sizes.${N}`)
// to avoid stomping unrelated localStorage data. Called from a mount
// effect inside the component, gated by `storageKey`.
const gcStaleSiblingKeys = (storageKey, currentCount) => {
  if (!storageKey || typeof window === 'undefined') return;
  // Only sweep sibling keys when this storageKey is itself one of the
  // count-suffixed entries (`...sizes.<digit>`). The leading prefix is
  // everything up to the final `.<digit>`.
  const m = /^(.*)\.(\d+)$/.exec(storageKey);
  if (!m) return;
  const prefix = m[1];
  try {
    for (let n = 1; n <= MAX_EDITOR_GROUPS_GC; n += 1) {
      if (n === currentCount) continue;
      window.localStorage.removeItem(`${prefix}.${n}`);
    }
  } catch {
    /* private mode / quota — non-fatal */
  }
};

const loadSizes = (storageKey, count) => {
  if (!storageKey || typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return sanitiseSizes(parsed, count);
  } catch {
    return null;
  }
};

const saveSizes = (storageKey, sizes) => {
  if (!storageKey || typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(sizes));
  } catch {
    /* quota / private mode — non-fatal */
  }
};

const useViewportIsMobile = () => {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.innerWidth < MOBILE_BREAKPOINT;
  });
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return isMobile;
};

const ResizableSplit = ({
  children,
  storageKey,
  defaultSizes,
  minSizes,
  disabled = false,
  className = '',
}) => {
  // Normalise children: array of React nodes, filter falsy.
  const panes = useMemo(
    () => (Array.isArray(children) ? children : [children]).filter(Boolean),
    [children],
  );
  const count = panes.length;

  // defaultSizes / minSizes might be shorter than count after a runtime
  // pane add — pad with sensible defaults. If they're longer, slice.
  const normalisedDefaults = useMemo(() => {
    const arr = (defaultSizes || []).slice(0, count);
    while (arr.length < count) arr.push(100 / count);
    return sanitiseSizes(arr, count) || Array(count).fill(100 / count);
  }, [defaultSizes, count]);

  const normalisedMins = useMemo(() => {
    const arr = (minSizes || []).slice(0, count);
    while (arr.length < count) arr.push(120);
    return arr;
  }, [minSizes, count]);

  const isMobile = useViewportIsMobile();
  const collapsed = isMobile || disabled;

  const containerRef = useRef(null);
  const dragRef = useRef(null); // { handleIndex, startX, startSizes, containerWidth }

  // Size state — percentages summing to 100.
  const [sizes, setSizes] = useState(() => {
    const stored = loadSizes(storageKey, count);
    return stored || normalisedDefaults;
  });

  // After first paint, re-clamp the loaded percentages against the
  // *actual* container width. A layout saved on a wide monitor can
  // restore a pane below its px floor on a smaller screen; only the
  // drag handler clamps, so without this fix the user has to wiggle
  // the divider to recover. Runs once per (storageKey, count) pair.
  useEffect(() => {
    const width = containerRef.current?.getBoundingClientRect().width || 0;
    if (width <= 0) return;
    setSizes((cur) => {
      if (cur.length !== count) return cur;
      const clamped = clampPercentagesToMinPixels(cur, normalisedMins, width);
      // Reference-equal short-circuit: skip the setState if clampr
      // returned the same array we passed in (no clamp needed).
      if (clamped === cur) return cur;
      // Float comparison — only re-render if any pane moved >0.5%.
      const moved = clamped.some((p, i) => Math.abs(p - cur[i]) > 0.5);
      return moved ? clamped : cur;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey, count]);

  // One-time GC sweep for stale per-count storage keys. Runs on mount
  // and whenever `count` changes so we always have at most one entry
  // alive in localStorage per chat-row instance.
  useEffect(() => {
    gcStaleSiblingKeys(storageKey, count);
  }, [storageKey, count]);

  // Re-hydrate when count changes (e.g. user splits the chat pane).
  // Try storage first under the (now wider/narrower) key; otherwise
  // fall back to defaults. Without this, splitting from 1→2 would
  // leave `sizes` length=1 and CSS grid would only show one pane.
  useEffect(() => {
    if (sizes.length === count) return;
    const stored = loadSizes(storageKey, count);
    setSizes(stored || normalisedDefaults);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count]);

  const onHandleMouseDown = useCallback(
    (handleIndex) => (e) => {
      if (collapsed) return;
      e.preventDefault();
      const containerWidth = containerRef.current?.getBoundingClientRect().width || 0;
      dragRef.current = {
        handleIndex,
        startX: e.clientX,
        startSizes: sizes.slice(),
        containerWidth,
      };
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
    },
    [sizes, collapsed],
  );

  useEffect(() => {
    if (collapsed) return undefined;

    const onMouseMove = (e) => {
      const drag = dragRef.current;
      if (!drag) return;
      const { handleIndex, startX, startSizes, containerWidth } = drag;
      if (containerWidth <= 0) return;
      const deltaPx = e.clientX - startX;
      const deltaPct = (deltaPx / containerWidth) * 100;

      // Grow pane[handleIndex] by deltaPct, shrink pane[handleIndex+1].
      const left = startSizes[handleIndex] + deltaPct;
      const right = startSizes[handleIndex + 1] - deltaPct;

      // Enforce px floors (convert min px → min pct via containerWidth).
      const minLeftPct = (normalisedMins[handleIndex] / containerWidth) * 100;
      const minRightPct = (normalisedMins[handleIndex + 1] / containerWidth) * 100;
      if (left < minLeftPct || right < minRightPct) return;

      const next = startSizes.slice();
      next[handleIndex] = left;
      next[handleIndex + 1] = right;
      setSizes(next);
    };

    const onMouseUp = () => {
      if (!dragRef.current) return;
      dragRef.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      // Persist *after* the drag ends — avoids a localStorage write per
      // mousemove tick.
      setSizes((cur) => {
        saveSizes(storageKey, cur);
        return cur;
      });
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
  }, [collapsed, normalisedMins, storageKey]);

  const onHandleDoubleClick = useCallback(() => {
    if (collapsed) return;
    setSizes(normalisedDefaults);
    saveSizes(storageKey, normalisedDefaults);
  }, [normalisedDefaults, storageKey, collapsed]);

  // Keyboard support on each handle: ArrowLeft/Right nudges the
  // split by 2% (or 5% with Shift), Home resets to defaults. Mirrors
  // the WAI-ARIA "separator" widget keyboard model. We re-use the
  // mousemove math: compute the deltaPct, apply to handleIndex and
  // handleIndex+1, enforce the same px floors via containerWidth.
  const onHandleKeyDown = useCallback(
    (handleIndex) => (e) => {
      if (collapsed) return;
      if (e.key === 'Home') {
        e.preventDefault();
        setSizes(normalisedDefaults);
        saveSizes(storageKey, normalisedDefaults);
        return;
      }
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const containerWidth = containerRef.current?.getBoundingClientRect().width || 0;
      if (containerWidth <= 0) return;
      const step = e.shiftKey ? 5 : 2;
      const deltaPct = e.key === 'ArrowRight' ? step : -step;
      setSizes((cur) => {
        if (cur.length !== count) return cur;
        const left = cur[handleIndex] + deltaPct;
        const right = cur[handleIndex + 1] - deltaPct;
        const minLeftPct = (normalisedMins[handleIndex] / containerWidth) * 100;
        const minRightPct = (normalisedMins[handleIndex + 1] / containerWidth) * 100;
        if (left < minLeftPct || right < minRightPct) return cur;
        const next = cur.slice();
        next[handleIndex] = left;
        next[handleIndex + 1] = right;
        // Persist immediately — there's no "keyup" boundary like the
        // mouseup that batches mouse-driven writes.
        saveSizes(storageKey, next);
        return next;
      });
    },
    [collapsed, count, normalisedDefaults, normalisedMins, storageKey],
  );

  // Build the grid-template-columns string. We interleave panes and
  // handles: `pane1 6px pane2 6px pane3`. Use minmax(0, Nfr) so flex
  // children inside the panes can shrink properly without pushing the
  // grid wider.
  const gridTemplateColumns = useMemo(() => {
    if (collapsed) return undefined;
    if (sizes.length !== count) return undefined; // Mid re-hydrate guard.
    const parts = [];
    for (let i = 0; i < count; i += 1) {
      parts.push(`minmax(0, ${sizes[i]}fr)`);
      if (i < count - 1) parts.push('6px');
    }
    return parts.join(' ');
  }, [collapsed, count, sizes]);

  if (collapsed) {
    return (
      <div className={`rs-root rs-stacked ${className}`.trim()} ref={containerRef}>
        {panes.map((pane, i) => (
          // eslint-disable-next-line react/no-array-index-key
          <div key={i} className="rs-pane">{pane}</div>
        ))}
      </div>
    );
  }

  // Interleave panes + drag handles into one flat children array. We
  // can't render two separate maps because CSS Grid lays children out
  // in document order, and the handle tracks have to alternate with
  // the pane tracks.
  const interleaved = [];
  for (let i = 0; i < count; i += 1) {
    interleaved.push(
      // eslint-disable-next-line react/no-array-index-key
      <div key={`pane-${i}`} className="rs-pane">{panes[i]}</div>,
    );
    if (i < count - 1) {
      interleaved.push(
        <div
          // eslint-disable-next-line react/no-array-index-key
          key={`handle-${i}`}
          className="rs-handle"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize pane"
          aria-valuenow={Math.round(sizes[i] ?? 0)}
          aria-valuemin={0}
          aria-valuemax={100}
          tabIndex={0}
          onMouseDown={onHandleMouseDown(i)}
          onDoubleClick={onHandleDoubleClick}
          onKeyDown={onHandleKeyDown(i)}
          title="Drag to resize · double-click to reset · arrow keys to nudge"
        />,
      );
    }
  }

  return (
    <div
      className={`rs-root ${className}`.trim()}
      ref={containerRef}
      style={{ gridTemplateColumns }}
    >
      {interleaved}
    </div>
  );
};

export default ResizableSplit;
