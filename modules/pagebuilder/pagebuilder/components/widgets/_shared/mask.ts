import type { CSSProperties } from 'react';

/**
 * An organic mask clips an image to a content-supplied SVG shape (e.g. the
 * BioGarden blob/egg shapes). The -webkit- prefixed keys keep Safari/iOS in
 * sync with the standard properties. Call once per widget render (not per
 * item) and share the returned object across mapped items.
 */
export function maskStyle(url: string): CSSProperties {
  return {
    maskImage: `url(${url})`,
    maskSize: '100% 100%',
    maskRepeat: 'no-repeat',
    WebkitMaskImage: `url(${url})`,
    WebkitMaskSize: '100% 100%',
    WebkitMaskRepeat: 'no-repeat',
  };
}

/**
 * Text color for content sitting on a colored band/card surface
 * (`surfaceColor`/`cardBg`). Tenants override `--pb-surface-contrast` when
 * their brand colors need dark-on-light contrast instead of white.
 */
export const SURFACE_CONTRAST = 'var(--pb-surface-contrast, #ffffff)';

/**
 * Theme-driven eyebrow case/tracking (`--pb-eyebrow-transform` /
 * `--pb-eyebrow-tracking`). Defaults keep eyebrows sentence-case; a tenant
 * sets `uppercase` + a tracking value for the small-caps eyebrow look.
 */
export const EYEBROW_CASE_STYLE: CSSProperties = {
  textTransform: 'var(--pb-eyebrow-transform, none)' as CSSProperties['textTransform'],
  letterSpacing: 'var(--pb-eyebrow-tracking, normal)',
};

/**
 * The ONE eyebrow ("subtitle") type spec, shared by every widget that renders
 * one — MediaObject (inline and banner), EyebrowSplitSection, Timeline (both
 * variants) and FeatureCards. Each of those used to hardcode its own size and
 * weight, so a single tenant showed four different eyebrows across one page.
 *
 * `size`/`weight` are the caller's PREVIOUS literal values and are used only
 * as the `var()` fallback, so a tenant that sets neither token renders exactly
 * as before; a tenant that sets `--pb-eyebrow-size`/`--pb-eyebrow-weight`
 * (BioGarden: 16px Medium) gets one consistent eyebrow everywhere.
 */
export function eyebrowTextStyle(size = '0.875rem', weight = '500'): CSSProperties {
  return {
    ...EYEBROW_CASE_STYLE,
    fontSize: `var(--pb-eyebrow-size, ${size})`,
    fontWeight: `var(--pb-eyebrow-weight, ${weight})` as CSSProperties['fontWeight'],
  };
}
