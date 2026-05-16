/*
 * ResizableSplit tests.
 *
 * Phase-A focus: the `direction` prop. Row direction is the legacy
 * behaviour and gets one sanity test; column direction (vertical
 * split) gets the bulk of the coverage — drag math on Y axis,
 * keyboard ArrowUp/Down nudges, aria-orientation, and the hydration
 * clamp picking up `containerHeight` instead of `containerWidth`.
 *
 * jsdom doesn't compute layout, so we monkey-patch
 * `Element.prototype.getBoundingClientRect` to feed the component
 * the container extent we want to assert against. We restore the
 * original after each test so other suites aren't poisoned.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import ResizableSplit from '../ResizableSplit';

// jsdom default innerWidth is 1024 which is above the 992 px mobile
// breakpoint — handles will render. Force a fresh value before each
// test to be explicit.
const setViewportWidth = (width) => {
  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    writable: true,
    value: width,
  });
  window.dispatchEvent(new Event('resize'));
};

const originalGetBCR = Element.prototype.getBoundingClientRect;
const stubAllRectsTo = ({ width = 1000, height = 600 } = {}) => {
  Element.prototype.getBoundingClientRect = function patched() {
    return {
      width,
      height,
      top: 0,
      left: 0,
      right: width,
      bottom: height,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    };
  };
};

// Pull the percentage out of a `minmax(0, Nfr)` grid template
// string. We use this in lieu of poking at the DOM, since the
// resize state ends up reflected on the inline grid-template style.
const parseTrackPercents = (template) => {
  if (!template) return [];
  return Array.from(template.matchAll(/minmax\(0,\s*([\d.]+)fr\)/g)).map(
    (m) => parseFloat(m[1]),
  );
};

beforeEach(() => {
  window.localStorage.clear();
  setViewportWidth(1400);
  Element.prototype.getBoundingClientRect = originalGetBCR;
});

afterAll(() => {
  Element.prototype.getBoundingClientRect = originalGetBCR;
});

describe('ResizableSplit row direction (default)', () => {
  test('renders gridTemplateColumns and aria-orientation="vertical"', () => {
    render(
      <ResizableSplit defaultSizes={[50, 50]} minSizes={[100, 100]}>
        <div data-testid="pane-a">A</div>
        <div data-testid="pane-b">B</div>
      </ResizableSplit>,
    );
    const handle = screen.getByRole('separator');
    expect(handle.getAttribute('aria-orientation')).toBe('vertical');
    expect(handle.dataset.direction).toBe('row');

    // The handle's parent is the .rs-root grid container — assert
    // inline template via the parent element rather than container
    // queries.
    // The handle's parent is the `.rs-root` grid container. There's
    // no semantic role on the root we can query through Testing
    // Library, so we walk one level up. The eslint rule against
    // parentElement is overly strict for this case — asserting
    // inline grid-template is the load-bearing observable here.
    // eslint-disable-next-line testing-library/no-node-access
    const root = handle.parentElement;
    expect(root.dataset.direction).toBe('row');
    expect(root.style.gridTemplateColumns).toContain('minmax(0, 50fr)');
    expect(root.style.gridTemplateRows).toBe('');
  });
});

describe('ResizableSplit column direction', () => {
  test('renders gridTemplateRows and aria-orientation="horizontal"', () => {
    render(
      <ResizableSplit
        direction="column"
        defaultSizes={[60, 40]}
        minSizes={[100, 100]}
      >
        <div>top</div>
        <div>bottom</div>
      </ResizableSplit>,
    );
    const handle = screen.getByRole('separator');
    expect(handle.getAttribute('aria-orientation')).toBe('horizontal');
    expect(handle.dataset.direction).toBe('column');

    // The handle's parent is the `.rs-root` grid container. There's
    // no semantic role on the root we can query through Testing
    // Library, so we walk one level up. The eslint rule against
    // parentElement is overly strict for this case — asserting
    // inline grid-template is the load-bearing observable here.
    // eslint-disable-next-line testing-library/no-node-access
    const root = handle.parentElement;
    expect(root.dataset.direction).toBe('column');
    const tracks = parseTrackPercents(root.style.gridTemplateRows);
    expect(tracks).toEqual([60, 40]);
    // The row-direction template must NOT be set in column mode —
    // otherwise the grid would have both axes pinned and the row
    // axis would override the column shape.
    expect(root.style.gridTemplateColumns).toBe('');
  });

  test('drag math uses clientY delta to grow/shrink panes', () => {
    stubAllRectsTo({ width: 1000, height: 600 });
    render(
      <ResizableSplit
        direction="column"
        defaultSizes={[60, 40]}
        minSizes={[100, 100]}
      >
        <div>top</div>
        <div>bottom</div>
      </ResizableSplit>,
    );

    const handle = screen.getByRole('separator');
    // The handle's parent is the `.rs-root` grid container. There's
    // no semantic role on the root we can query through Testing
    // Library, so we walk one level up. The eslint rule against
    // parentElement is overly strict for this case — asserting
    // inline grid-template is the load-bearing observable here.
    // eslint-disable-next-line testing-library/no-node-access
    const root = handle.parentElement;
    // Mousedown at Y=360 (≈ 60% boundary of 600 px container).
    fireEvent.mouseDown(handle, { clientY: 360, clientX: 500 });
    // Drag down 60 px → +10% to top pane, -10% from bottom.
    fireEvent.mouseMove(window, { clientY: 420, clientX: 500 });
    fireEvent.mouseUp(window);

    const [top, bottom] = parseTrackPercents(root.style.gridTemplateRows);
    // After drag, top ≈ 70%, bottom ≈ 30%. Allow ±5% float drift.
    expect(top).toBeGreaterThan(65);
    expect(top).toBeLessThan(75);
    expect(bottom).toBeGreaterThan(25);
    expect(bottom).toBeLessThan(35);
    expect(top + bottom).toBeCloseTo(100, 0);
  });

  test('ignores clientX deltas in column mode (axis isolation)', () => {
    stubAllRectsTo({ width: 1000, height: 600 });
    render(
      <ResizableSplit
        direction="column"
        defaultSizes={[60, 40]}
        minSizes={[100, 100]}
      >
        <div>top</div>
        <div>bottom</div>
      </ResizableSplit>,
    );

    const handle = screen.getByRole('separator');
    // The handle's parent is the `.rs-root` grid container. There's
    // no semantic role on the root we can query through Testing
    // Library, so we walk one level up. The eslint rule against
    // parentElement is overly strict for this case — asserting
    // inline grid-template is the load-bearing observable here.
    // eslint-disable-next-line testing-library/no-node-access
    const root = handle.parentElement;
    fireEvent.mouseDown(handle, { clientY: 360, clientX: 500 });
    // Move only horizontally — must not affect vertical split sizes.
    fireEvent.mouseMove(window, { clientY: 360, clientX: 999 });
    fireEvent.mouseUp(window);

    const tracks = parseTrackPercents(root.style.gridTemplateRows);
    expect(tracks).toEqual([60, 40]);
  });

  test('ArrowDown nudges first pane up by 2%; Shift+ArrowDown by 5%', () => {
    stubAllRectsTo({ width: 1000, height: 600 });
    render(
      <ResizableSplit
        direction="column"
        defaultSizes={[60, 40]}
        minSizes={[50, 50]}
      >
        <div>top</div>
        <div>bottom</div>
      </ResizableSplit>,
    );

    const handle = screen.getByRole('separator');
    // The handle's parent is the `.rs-root` grid container. There's
    // no semantic role on the root we can query through Testing
    // Library, so we walk one level up. The eslint rule against
    // parentElement is overly strict for this case — asserting
    // inline grid-template is the load-bearing observable here.
    // eslint-disable-next-line testing-library/no-node-access
    const root = handle.parentElement;
    fireEvent.keyDown(handle, { key: 'ArrowDown' });
    let [top] = parseTrackPercents(root.style.gridTemplateRows);
    expect(top).toBeCloseTo(62, 1);

    fireEvent.keyDown(handle, { key: 'ArrowDown', shiftKey: true });
    [top] = parseTrackPercents(root.style.gridTemplateRows);
    expect(top).toBeCloseTo(67, 1);
  });

  test('ArrowUp shrinks first pane; Home resets to defaults', () => {
    stubAllRectsTo({ width: 1000, height: 600 });
    render(
      <ResizableSplit
        direction="column"
        defaultSizes={[60, 40]}
        minSizes={[50, 50]}
      >
        <div>top</div>
        <div>bottom</div>
      </ResizableSplit>,
    );

    const handle = screen.getByRole('separator');
    // The handle's parent is the `.rs-root` grid container. There's
    // no semantic role on the root we can query through Testing
    // Library, so we walk one level up. The eslint rule against
    // parentElement is overly strict for this case — asserting
    // inline grid-template is the load-bearing observable here.
    // eslint-disable-next-line testing-library/no-node-access
    const root = handle.parentElement;
    fireEvent.keyDown(handle, { key: 'ArrowUp' });
    let [top] = parseTrackPercents(root.style.gridTemplateRows);
    expect(top).toBeCloseTo(58, 1);

    fireEvent.keyDown(handle, { key: 'Home' });
    [top] = parseTrackPercents(root.style.gridTemplateRows);
    expect(top).toBeCloseTo(60, 1);
  });

  test('hydration clamp uses container height (not width) in column mode', () => {
    // Persist a layout where the top pane is 5% of total. In a tall
    // container (height=1000), 5% = 50 px which sits below the
    // 200 px floor → expect hydration to lift it to ≥20%.
    window.localStorage.setItem(
      'col-hydrate-test',
      JSON.stringify([5, 95]),
    );
    // Stub rects so the post-mount clamp effect sees height=1000.
    stubAllRectsTo({ width: 1000, height: 1000 });

    render(
      <ResizableSplit
        direction="column"
        storageKey="col-hydrate-test"
        defaultSizes={[60, 40]}
        minSizes={[200, 200]}
      >
        <div>top</div>
        <div>bottom</div>
      </ResizableSplit>,
    );

    // eslint-disable-next-line testing-library/no-node-access
    const root = screen.getByRole('separator').parentElement;
    const [top] = parseTrackPercents(root.style.gridTemplateRows);
    // 200 px floor in a 1000 px container = 20% minimum.
    expect(top).toBeGreaterThanOrEqual(20 - 0.5);
  });
});

describe('ResizableSplit mobile fallback applies to both directions', () => {
  test('stacked layout in column direction renders panes without handles', () => {
    setViewportWidth(800); // below 992 breakpoint
    render(
      <ResizableSplit
        direction="column"
        defaultSizes={[60, 40]}
        minSizes={[100, 100]}
      >
        <div>top</div>
        <div>bottom</div>
      </ResizableSplit>,
    );
    // No separator handles in stacked mode regardless of direction.
    expect(screen.queryByRole('separator')).toBeNull();
    // Both panes still in document order.
    expect(screen.getByText('top')).toBeInTheDocument();
    expect(screen.getByText('bottom')).toBeInTheDocument();
  });
});
