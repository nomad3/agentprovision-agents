/*
 * Privacy-respecting marketing analytics — Mk-1 of the visibility roadmap.
 *
 * Loads the Plausible standalone script only when
 * REACT_APP_PLAUSIBLE_DOMAIN is set. Dev / preview / self-hosted
 * tenants without that env var are no-ops — no third-party requests,
 * no fingerprinting, no PII.
 *
 * Distinct from src/services/analytics.js which talks to our own
 * /analytics/* tenant-stats API. This file is for landing-page CTA
 * attribution only.
 *
 * Usage:
 *   import { initMarketingAnalytics, track } from '../services/marketingAnalytics';
 *   initMarketingAnalytics();
 *   track('cta_get_started_click', { location: 'hero' });
 */

let _initialized = false;


function _enabled() {
  const domain = process.env.REACT_APP_PLAUSIBLE_DOMAIN;
  return Boolean(domain && typeof domain === 'string' && domain.trim());
}


/**
 * Pick the right Plausible `data-domain` value at runtime.
 *
 * The SAME SPA bundle is served on both `agentprovision.com` and
 * `alpha.agentprovision.com`. If we used the build-time env var
 * verbatim, every `alpha_*` event would land in the main site's
 * Plausible property (or vice versa). Sniffing the live hostname
 * keeps each subdomain's events in its own dashboard.
 *
 * Honors an explicit `REACT_APP_PLAUSIBLE_DOMAIN_ALPHA` override when
 * set; otherwise derives the alpha domain by replacing the leading
 * label of the apex domain.
 *
 * PR #450 review IMPORTANT I2.
 */
function _resolveDomain() {
  const apex = process.env.REACT_APP_PLAUSIBLE_DOMAIN.trim();
  if (typeof window === 'undefined' || !window.location) return apex;
  const host = window.location.hostname;
  if (host.startsWith('alpha.')) {
    return (process.env.REACT_APP_PLAUSIBLE_DOMAIN_ALPHA || '').trim()
      || `alpha.${apex}`;
  }
  return apex;
}


export function initMarketingAnalytics() {
  if (_initialized) return;
  if (typeof window === 'undefined') return;
  if (!_enabled()) return;

  const domain = _resolveDomain();
  const host = (process.env.REACT_APP_PLAUSIBLE_HOST || 'https://plausible.io').trim();

  if (document.querySelector('script[data-domain-marker="plausible"]')) {
    _initialized = true;
    return;
  }

  const s = document.createElement('script');
  s.defer = true;
  s.src = `${host}/js/script.js`;
  s.setAttribute('data-domain', domain);
  s.setAttribute('data-domain-marker', 'plausible');
  document.head.appendChild(s);

  // Queue stub — track() calls before the script loads still work.
  window.plausible = window.plausible || function () {
    (window.plausible.q = window.plausible.q || []).push(arguments);
  };

  _initialized = true;
}


export function track(eventName, props) {
  if (typeof window === 'undefined') return;
  if (!_enabled()) return;
  if (!eventName || typeof eventName !== 'string') return;

  if (typeof window.plausible !== 'function') {
    window.plausible = function () {
      (window.plausible.q = window.plausible.q || []).push(arguments);
    };
  }

  if (props && typeof props === 'object') {
    window.plausible(eventName, { props });
  } else {
    window.plausible(eventName);
  }
}


// Test-only helper. Keeps the production API surface lean.
export function _resetForTest() {
  _initialized = false;
}
