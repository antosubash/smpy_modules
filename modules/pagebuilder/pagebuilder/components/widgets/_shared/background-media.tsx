import { cn, decorativeAriaProps } from '../../../utils/widgetUtils';
import { SIZES_FULL, srcsetAttrs } from './image-srcset';

export type BackgroundMediaOverlay = 'none' | 'subtle' | 'dark';
export type BackgroundMediaFallback = 'gradient-mesh' | 'solid';

export type BackgroundMediaProps = {
  imageUrl: string;
  imageAlt: string;
  overlay?: BackgroundMediaOverlay;
  fallback?: BackgroundMediaFallback;
  /**
   * CSS `object-position` for the cover-fitted photo. Callers pass a themeable
   * token so a tenant can choose which part of a tall photo survives the crop
   * (BioGarden's hero is a 1440x1920 sky-over-meadow shot that the Figma
   * anchors to the top; centered, the sky is cut away). Omitted = centered.
   */
  objectPosition?: string;
  /** Variant srcset recorded at pick time (see _shared/image-srcset.ts). */
  imageSrcset?: string;
};

// The "dark" scrim strength is tenant-tunable: GCA's Figma hero is nearly
// un-dimmed (see `--pb-hero-overlay` in gca.css); the fallback keeps the
// original 55% black for tenants that don't set the token.
const OVERLAY_CLASSES: Record<Exclude<BackgroundMediaOverlay, 'none'>, string> = {
  subtle: 'bg-black/30',
  dark: 'bg-[color:var(--pb-hero-overlay,rgb(0_0_0/0.55))]',
};

// Hoisted: a fresh style object per render would defeat React's prop-equality
// fast-path and re-trigger style-attribute writes on every editor keystroke.
const MESH_STYLE = {
  background:
    'radial-gradient(at 18% 28%, #c084fc 0px, transparent 50%), ' +
    'radial-gradient(at 82% 18%, #ec4899 0px, transparent 50%), ' +
    'radial-gradient(at 72% 88%, #6366f1 0px, transparent 50%), ' +
    '#2e1065',
} as const;

export function BackgroundMedia({
  imageUrl,
  imageAlt,
  overlay = 'none',
  fallback = 'gradient-mesh',
  objectPosition,
  imageSrcset,
}: BackgroundMediaProps) {
  // data-pb-* attributes are stable selectors for tests and CMS-side analytics.
  return (
    <>
      {imageUrl ? (
        <img
          src={imageUrl}
          {...srcsetAttrs(imageSrcset, SIZES_FULL)}
          alt={imageAlt ?? ''}
          {...decorativeAriaProps(imageAlt)}
          loading="lazy"
          className="absolute inset-0 -z-10 w-full h-full object-cover"
          style={objectPosition ? { objectPosition } : undefined}
        />
      ) : fallback === 'gradient-mesh' ? (
        <div
          data-pb-fallback="gradient-mesh"
          className="absolute inset-0 -z-10"
          style={MESH_STYLE}
        />
      ) : (
        <div data-pb-fallback="solid" className="absolute inset-0 -z-10 bg-slate-900" />
      )}
      {overlay !== 'none' && (
        <div
          data-pb-overlay={overlay}
          className={cn('absolute inset-0 -z-10', OVERLAY_CLASSES[overlay])}
        />
      )}
    </>
  );
}
