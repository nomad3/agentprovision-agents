// Smoke test for the i18n bootstrap. Just importing the module exercises
// `i18n.init()` and the resource registration paths.

import i18n from '../i18n';

describe('i18n bootstrap', () => {
  test('initializes with at least en + es', () => {
    expect(i18n.options.supportedLngs).toEqual(expect.arrayContaining(['en', 'es']));
    expect(i18n.options.fallbackLng).toEqual(expect.arrayContaining(['en']));
  });

  test('registers a wide set of namespaces', () => {
    const ns = i18n.options.ns;
    expect(ns).toEqual(expect.arrayContaining(['common', 'auth', 'workflows', 'memory']));
  });

  test('default namespace is common', () => {
    expect(i18n.options.defaultNS).toBe('common');
  });
});
