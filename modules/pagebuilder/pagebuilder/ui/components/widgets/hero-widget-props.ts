/** Prop shape for HeroWidget — extracted so hero-widget.tsx stays under the
 *  repo's 300-line cap. Re-exported from there, so importers are unaffected. */

export type HeroWidgetProps = {
  eyebrow: string;
  title: string;
  subtitle: string;
  logoUrl: string;
  logoAlt: string;
  imageUrl: string;
  imageAlt: string;
  /** Variant srcset recorded at pick time (see _shared/image-srcset.ts). */
  imageSrcset?: string;
  /**
   * Organic mask (SVG url, from the tenant's content) applied to the side
   * image in the right/left layouts. Empty = the standard rounded media.
   */
  imageMaskUrl?: string;
  /**
   * "native" renders supplied transparent artwork exactly as-is — no mask, no
   * crop — for a photo already cut to its final organic shape. Preferred over
   * `imageMaskUrl`, which re-derives the silhouette from a hand-kept SVG.
   */
  imageShape?: 'rounded' | 'native';
  imagePosition: 'background' | 'right' | 'left';
  primaryLabel: string;
  primaryHref: string;
  secondaryLabel: string;
  secondaryHref: string;
  overlay: boolean;
  align: 'left' | 'center';
  surface: 'plain' | 'card';
};
