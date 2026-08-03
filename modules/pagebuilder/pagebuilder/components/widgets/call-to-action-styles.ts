/** Heading styles and band shell for the call-to-action widget. */

import type { CSSProperties } from 'react';

export const DISPLAY_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
};

// Hoisted band-heading styles (constant tokens only). The fallback clamps
// reproduce the prior `text-2xl sm:text-3xl lg:text-4xl` responsive steps:
// 24px on phones, 30px at 640px, 36px at 1024px.
export const SOFT_HEADING_STYLE: CSSProperties = {
  ...DISPLAY_STYLE,
  color: '#1a353e',
  fontSize: 'var(--pb-heading-lg, clamp(1.5rem, 1.25rem + 1.5625vw, 2.25rem))',
};

export const LIME_HEADING_STYLE: CSSProperties = {
  ...DISPLAY_STYLE,
  color: '#1a353e',
  fontSize: 'var(--pb-heading-xl, clamp(1.5rem, 1.25rem + 1.5625vw, 2.25rem))',
};

// Inset bands (lime / soft) share one shell so they line up with every other
// contained section at the same content width across breakpoints.
export const BAND_SHELL = 'container mx-auto px-4 py-12 sm:px-6 lg:px-8';
