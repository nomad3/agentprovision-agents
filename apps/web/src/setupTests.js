// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';

// jsdom (used by jest under CRA) doesn't ship structuredClone yet, but
// some libraries we depend on (e.g. @dagrejs/dagre) call it during
// graph layout. Polyfill it with a JSON round-trip — tests don't
// exercise non-JSON-safe data through these paths.
if (typeof globalThis.structuredClone !== 'function') {
  globalThis.structuredClone = (val) => JSON.parse(JSON.stringify(val));
}

// jsdom doesn't implement matchMedia, which Bootstrap and a few other
// components rely on. Provide a stub so component renders don't blow up.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

// jsdom doesn't have ResizeObserver, but reactflow uses it.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
