import React from 'react';

/**
 * BrandMark — inline SVG wordmark for the auth pages (Login, Register,
 * Reset Password).
 *
 * Why inline SVG instead of an <img> referencing /assets/brand/*.png:
 * the historical PNGs at apps/web/public/assets/brand/ap-logo-* still
 * carry the pre-rebrand wolfpoint.ai artwork from before the
 * agentprovision rename (confirmed 2026-05-10 — see memory
 * product_is_agentprovision.md). Swapping the bytes requires a
 * designed asset; rendering the wordmark as text + a geometric mark
 * inline removes that blocker so the auth pages stop showing the
 * wrong brand TODAY. Drop a designed logo over this by reverting the
 * three callsites (LoginPage, RegisterPage, ResetPasswordPage) to an
 * <img src={`${process.env.PUBLIC_URL}/assets/brand/<new>.png`} />.
 *
 * Sizing: the component takes an optional `height` prop (default 36px)
 * so the auth-page header (which used a 120px-wide PNG) stays visually
 * similar without doing absolute width math.
 */
const BrandMark = ({ height = 36 }) => {
  return (
    <svg
      role="img"
      aria-label="agentprovision.com"
      height={height}
      viewBox="0 0 320 56"
      style={{ display: 'block', margin: '0 auto', maxWidth: '100%' }}
    >
      {/* Geometric mark — a stack of three diagonals forming an `alpha`
          glyph silhouette. Deliberately abstract; no animal artwork
          to avoid reading as the old wolf logo. Primary brand colour
          uses the same blue we already ship across the dashboard
          (.ap-primary CSS var resolves to #2b7de9). */}
      <g transform="translate(0, 8)">
        <rect x="0" y="0" width="40" height="40" rx="8" fill="#2b7de9" />
        <path
          d="M10 28 L20 12 L30 28 M14 22 H26"
          stroke="white"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      </g>
      {/* Wordmark */}
      <text
        x="52"
        y="36"
        fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
        fontSize="22"
        fontWeight="600"
        fill="#1a2433"
        letterSpacing="-0.3"
      >
        agentprovision
      </text>
      <text
        x="52"
        y="50"
        fontFamily="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
        fontSize="10"
        fontWeight="500"
        fill="#64748b"
        letterSpacing="1.2"
      >
        AGENT NETWORK
      </text>
    </svg>
  );
};

export default BrandMark;
