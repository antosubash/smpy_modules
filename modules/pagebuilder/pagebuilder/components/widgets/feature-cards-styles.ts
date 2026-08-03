/** Icon map and style tables for the feature-cards widget. */

import type { CSSProperties } from 'react';

import type { SolidIconProps } from './_internal/solid-icons';
import {
  ChartAreaSolid,
  MagnifyingGlassChartSolid,
  PawSolid,
  TemperatureSolid,
  TreeSolid,
  WaterSolid,
} from './_internal/solid-icons';

export const ICON_MAP: Record<string, (props: SolidIconProps) => React.JSX.Element> = {
  chart: ChartAreaSolid,
  search: MagnifyingGlassChartSolid,
  thermometer: TemperatureSolid,
  tree: TreeSolid,
  paw: PawSolid,
  waves: WaterSolid,
};

export type FeatureCardItem = {
  title: string;
  description: string;
  icon: string;
  iconBg: string;
  iconUrl: string;
  /**
   * Alt text for `iconUrl`. Needed when the image IS the card's visible title
   * (BioGarden's wordmark cards leave `title` empty) — otherwise the card link
   * is announced without its name. Empty = decorative.
   */
  iconAlt?: string;
  href: string;
  /** Optional category label shown top-right of the card (e.g. outputs type). */
  tag?: string;
  /**
   * Optional CSS color filling the whole card (e.g. a tenant's program
   * color). When set, the card renders with white text and the icon image
   * becomes a larger wordmark-style lockup.
   */
  cardBg?: string;
};

export type FeatureCardsWidgetProps = {
  eyebrow: string;
  title: string;
  subtitle: string;
  linkLabel: string;
  linkHref: string;
  /** Per-card link label (defaults to "Learn more"; e.g. "View output"). */
  cardLinkLabel: string;
  /** Section surface: plain (default) or a soft grey rounded panel. */
  surface: 'default' | 'muted';
  /** Card surface: white with a border (default) or a soft grey panel. */
  cardSurface: 'default' | 'muted';
  columns: '2' | '3' | '4';
  items: FeatureCardItem[];
};

export const COLS_CLASS: Record<FeatureCardsWidgetProps['columns'], string> = {
  '2': 'sm:grid-cols-2',
  '3': 'sm:grid-cols-2 lg:grid-cols-3',
  '4': 'sm:grid-cols-2 lg:grid-cols-4',
};

export const DISPLAY_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
  color: 'var(--pb-heading-color)',
};

// Hoisted (not per-render) style objects — all values are constant tokens.
// The heading fallback clamp reproduces the prior `text-3xl sm:text-4xl`
// steps: 30px below 640px, 36px from the 640px breakpoint up.
export const HEADING_LG_STYLE: CSSProperties = {
  ...DISPLAY_STYLE,
  fontSize: 'var(--pb-heading-lg, clamp(1.875rem, 1.3125rem + 2.34375vw, 2.25rem))',
};

export const EYEBROW_STYLE: CSSProperties = {
  color: 'var(--pb-body-color)',
  fontSize: 'var(--pb-eyebrow-size, 0.875rem)',
};

export const CARD_TITLE_STYLE: CSSProperties = {
  fontFamily: 'var(--pb-display-font)',
  fontWeight:
    'var(--pb-card-title-weight, var(--pb-display-weight))' as CSSProperties['fontWeight'],
  fontSize: 'var(--pb-card-title-size, 1.125rem)',
  color: 'var(--pb-heading-color)',
};

export const CARD_BODY_STYLE: CSSProperties = {
  color: 'var(--pb-body-color)',
  fontSize: 'var(--pb-card-body-size, 0.875rem)',
};

// The bold lead-in line above a coloured card's description (BioGarden's
// "Jetzt anmelden"). Sized by its own token so it can be the Figma's 22px
// without dragging the body copy with it; the fallback is the previous 1rem.
export const CARD_TAG_STYLE: CSSProperties = {
  fontSize: 'var(--pb-card-tag-size, 1rem)',
};
