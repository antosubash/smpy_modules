import type { CSSProperties } from 'react';
import { cn } from '../../../utils/widgetUtils';
import { AccentText } from '../_internal/accent-text';

export type HeadingLevel = 'h1' | 'h2' | 'h3';
export type HeadingSize = 'xl' | 'lg' | 'md';
export type HeadingTone = 'default' | 'inverse';

export type HeadingProps = {
  as: HeadingLevel;
  size: HeadingSize;
  text: string;
  align?: 'left' | 'center';
  tone?: HeadingTone;
  /**
   * Opt-in "accent" treatment for page-hero titles. Tenants can give the hero
   * title a distinct weight/style (e.g. GCA's SemiBold *Italic* H1) via the
   * `--pb-hero-title-*` tokens. Falls back to the normal display weight / an
   * upright style, so tenants that don't set the tokens are unaffected.
   */
  accent?: boolean;
};

// Display line-height is tenant-tunable: Mowing's Figma uses 1.2 for every
// heading level; the fallbacks reproduce the prior tight leading, so tenants
// that don't set `--pb-heading-leading` (GCA, Recodo) render unchanged.
const SIZE_CLASSES: Record<HeadingSize, string> = {
  xl: 'leading-[var(--pb-heading-leading,1.1)]',
  lg: 'leading-[var(--pb-heading-leading,1.1)]',
  md: 'leading-[var(--pb-heading-leading,1.25)]',
};

// Font sizes are tenant-themeable via `--pb-heading-*`; the clamp() fallbacks
// reproduce the previous responsive Tailwind steps, so tenants that don't set
// the tokens render unchanged. A tenant (e.g. Mowing) can scale the whole
// display hierarchy up by overriding these tokens in its theme vars.
const SIZE_FONT: Record<HeadingSize, string> = {
  xl: 'var(--pb-heading-xl, clamp(2.25rem, 1.4rem + 3.6vw, 3.75rem))',
  lg: 'var(--pb-heading-lg, clamp(1.875rem, 1.3rem + 2.5vw, 3rem))',
  md: 'var(--pb-heading-md, clamp(1.5rem, 1.2rem + 1.4vw, 1.875rem))',
};

// `inverse` keeps white on dark/colored backgrounds; `default` takes the
// per-tenant heading color from the --pb-* tokens via `style`.
const TONE_CLASSES: Record<HeadingTone, string> = {
  default: '',
  inverse: 'text-white',
};

// Display weight/tracking/font come from per-tenant page-builder tokens
// (Recodo defaults in styles.css `:root`, GCA overrides in `.gca-root`).
const DISPLAY_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
};

// Hero-title "accent" overrides: a distinct weight + (optional) italic style,
// each falling back so non-GCA tenants render an upright display-weight title.
const ACCENT_STYLE: CSSProperties = {
  fontWeight:
    'var(--pb-hero-title-weight, var(--pb-display-weight))' as CSSProperties['fontWeight'],
  fontStyle: 'var(--pb-hero-title-style, normal)' as CSSProperties['fontStyle'],
};

export function Heading({ as, size, text, align, tone = 'default', accent = false }: HeadingProps) {
  if (!text || text.trim() === '') return null;
  const Tag = as;
  // Hero titles (accent) may take a dedicated size token so a tenant can make
  // its page-hero H1 larger than section headings that share the same `size`
  // (e.g. Mowing: hero 64px while SectionIntro `lg` stays 48px). Falls back to
  // the normal size token, so tenants that don't set it render unchanged.
  const fontSize = accent ? `var(--pb-hero-title-size, ${SIZE_FONT[size]})` : SIZE_FONT[size];
  const base: CSSProperties = {
    ...(accent ? { ...DISPLAY_STYLE, ...ACCENT_STYLE } : DISPLAY_STYLE),
    fontSize,
  };
  const style: CSSProperties =
    tone === 'inverse' ? base : { ...base, color: 'var(--pb-heading-color)' };
  return (
    <Tag
      className={cn(SIZE_CLASSES[size], TONE_CLASSES[tone], align === 'center' && 'text-center')}
      style={style}
    >
      <AccentText text={text} />
    </Tag>
  );
}
