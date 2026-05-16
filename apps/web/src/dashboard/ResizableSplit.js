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

const sanitiseSizes = (sizes, count) => {
  if (!Array.isArray(sizes) || sizes.length !== count) return null;
  if (!sizes.every((n) => typeof n === 'number' && Number.isFinite(n) && n > 0)) return null;
  const sum = sizes.reduce((a, b) => a + b, 0);
  if (sum <= 0) return null;
  // Normalise to exactly 100.
  return sizes.map((n) => (n / sum) * 100);
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

  // Size state — percentages summing to 100.
  const [sizes, setSizes] = useState(() => {
    const stored = loadSizes(storageKey, count);
    return stored || normalisedDefaults;
  });

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

  const containerRef = useRef(null);
  const dragRef = useRef(null); // { handleIndex, startX, startSizes, containerWidth }

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
          onMouseDown={onHandleMouseDown(i)}
          onDoubleClick={onHandleDoubleClick}
          title="Drag to resize · double-click to reset"
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
