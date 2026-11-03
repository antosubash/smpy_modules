/** Props type and grid/heading tables for the media-object widget. */

import type { CSSProperties } from 'react';

export type MediaObjectWidgetProps = {
  imageUrl: string;
  imageAlt: string;
  /** Variant srcset recorded at pick time (see _shared/image-srcset.ts). */
  imageSrcset?: string;
  imagePosition: 'left' | 'right';
  heading: string;
  body: string;
  linkLabel: string;
  linkHref: string;
  logos?: { src: string; alt: string }[];
  /** "narrow" constrains the heading so a short title wraps to two lines. */
  headingWidth?: 'auto' | 'narrow';
  /**
   * Organic mask (SVG url, supplied by the tenant's content) applied to the
   * side image. When set the image is clipped to the shape and loses its
   * rounded corners. Empty = the plain rounded image (unchanged).
   */
  imageMaskUrl?: string;
  /**
   * How the side image is framed. "rounded" is the default rounded rectangle.
   * "native" renders the file exactly as supplied — no crop, no rounding, no
   * mask — for transparent artwork that is already cut to its final shape.
   * Preferred over `imageMaskUrl`: a supplied cut-out is pixel-accurate, where
   * a mask re-derives the silhouette and has to be kept in sync by hand.
   */
  imageShape?: 'rounded' | 'native';
  /** Chip overlaid top-left on the image (e.g. a location tag). */
  imageTag?: string;
  /** CSS color for the image tag chip (text stays surface-contrast). */
  imageTagColor?: string;
  /**
   * Organic mask for the image tag. Set it and the tag renders as the Figma's
   * tilted blob overhanging the photo's top-left instead of a rounded pill.
   */
  imageTagMaskUrl?: string;
  /**
   * Transparent artwork for the image tag, used INSTEAD of `imageTagMaskUrl` +
   * `imageTagColor`: the file carries the tag's shape and colour, and only the
   * upright label is drawn over it.
   */
  imageTagImageUrl?: string;
  /** Small pill rendered above the heading (e.g. a date/time or a count). */
  datePill?: string;
  /** CSS color for the date pill (text stays surface-contrast). */
  datePillColor?: string;
  surface: 'default' | 'dark' | 'muted';
  /**
   * Optional CSS color for the band background (e.g. a tenant's program
   * color). When set, the band renders like the dark surface (white text)
   * but on this color instead of `--secondary`.
   */
  surfaceColor?: string;
  /** Small label in the first grid column (grid/banner layouts only). */
  eyebrow?: string;
  /**
   * Structured points rendered under `body` as a marker list — the Figma's
   * "Warum mitmachen?" (title + explanation per point) and "Netzwerk" (bare
   * names). Kept separate from `body`, which is one text block and can only
   * flatten such a list into indistinguishable lines.
   */
  bullets?: { title: string; body?: string }[];
  /**
   * Optional CSS max-width for the body paragraph alone (the Figma caps the
   * event-card copy at 478px inside a wider text column). Empty = unconstrained.
   */
  bodyMaxWidth?: string;
  /**
   * Trailing credit line under the body, set semibold italic — the Figma's
   * "In Zusammenarbeit mit …" on each event card.
   */
  footnote?: string;
  /** Point-title size: `md` = 20px, `lg` = 24px (both from the Figma). */
  bulletSize?: 'md' | 'lg';
  /**
   * Render `linkLabel` as the tenant's outlined CTA button rather than an
   * inline text link — the Figma draws the "Projekt-Flyer herunterladen"
   * action on the green band as a bordered pill, not a link.
   */
  linkVariant?: 'link' | 'button';
  /** Show the design's small square marker before each point. */
  bulletMarker?: 'square' | 'none';
  /**
   * "half" is the legacy 50/50 flex split. "grid" aligns image and text to the
   * 12-column page grid (Mowing Figma: image spans 6 columns, text sits at the
   * 2nd column for image-right / ends at the 12th for image-left). "banner"
   * drops the side image: eyebrow left, text at the 4th column, with the image
   * (e.g. a partner-logo strip) rendered underneath the text.
   */
  layout?: 'half' | 'grid' | 'banner';
  /** Text column width on the page grid: xs ≈ 315px, sm ≈ 432px, md ≈ 546px. */
  textWidth?: 'auto' | 'xs' | 'sm' | 'md';
};

// Display tokens for the heading — weight/tracking/font come from the per-tenant
// page-builder theme (see styles.css `:root` for Recodo defaults and `.gca-root`
// for the GCA overrides). Color is overridden to white in the dark surface. The
// font-size reads `--pb-heading-lg` but falls back to the prior size, so tenants
// that don't set the token (GCA, Recodo) render unchanged.

export function headingStyle(
  inverse: boolean,
  layout: MediaObjectWidgetProps['layout'] = 'half',
): CSSProperties {
  return {
    fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
    letterSpacing: 'var(--pb-display-tracking)',
    fontFamily: 'var(--pb-display-font)',
    // The banner reads the section-heading size (`--pb-heading-md`, Mowing →
    // 40px) so its title matches the other eyebrow sections on the page.
    fontSize:
      layout === 'banner'
        ? 'var(--pb-heading-md, clamp(1.875rem, 1.3rem + 1.4vw, 2.5rem))'
        : 'var(--pb-heading-lg, clamp(1.875rem, 1.3rem + 1.8vw, 2.25rem))',
    color: inverse ? 'var(--pb-surface-contrast, #ffffff)' : 'var(--pb-heading-color)',
  };
}

// 12-col grid placement (gap 24px): the text column spans 3/4/5 columns and the
// image spans the design's 6 columns for image-right, or fills the columns left
// of the text for image-left — both text placements end flush with the Figma
// grid (image-right text starts at col 2; image-left text ends before col 12).
export const GRID_TEXT: Record<'xs' | 'sm' | 'md', { right: string; left: string; max: string }> = {
  xs: {
    right: 'lg:col-start-2 lg:col-span-3',
    left: 'lg:col-start-9 lg:col-span-3',
    max: 'max-w-[315px]',
  },
  sm: {
    right: 'lg:col-start-2 lg:col-span-4',
    left: 'lg:col-start-8 lg:col-span-4',
    max: 'max-w-[432px]',
  },
  md: {
    right: 'lg:col-start-2 lg:col-span-5',
    left: 'lg:col-start-7 lg:col-span-5',
    max: 'max-w-[546px]',
  },
};

export const GRID_IMAGE: Record<'xs' | 'sm' | 'md', { right: string; left: string }> = {
  xs: {
    right: 'lg:col-start-7 lg:col-span-6',
    left: 'lg:col-start-1 lg:col-span-7',
  },
  sm: {
    right: 'lg:col-start-7 lg:col-span-6',
    left: 'lg:col-start-1 lg:col-span-6',
  },
  md: {
    right: 'lg:col-start-7 lg:col-span-6',
    left: 'lg:col-start-1 lg:col-span-5',
  },
};
