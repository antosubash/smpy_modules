/** Timeline types and marker geometry. Split out so the widget's field
 *  definitions and its render can import them without a cycle, and so all
 *  three stay under the 300-line cap. */

export type TimelineItem = {
  marker: string;
  title: string;
  body: string;
  /**
   * Trailing emphasis line under the body (the design's bold-italic date, e.g.
   * "September & Oktober 2026"). Kept separate from `body` so it can sit on its
   * own line rather than running into the sentence before it.
   */
  meta?: string;
  /** Blobs variant only: CSS color filling the organic blob. */
  color?: string;
  /**
   * Blobs variant only: per-entry organic mask (SVG url), overriding the
   * section-wide `blobMaskUrl`. The BioGarden Figma draws each milestone as a
   * DIFFERENT shape, so one mask for the whole row was visibly wrong.
   */
  shapeMaskUrl?: string;
  /**
   * Supplied transparent artwork for the blob, used INSTEAD of
   * `shapeMaskUrl` + `color`: the file carries the shape AND its fill, and the
   * entry's copy is laid out over it. Preferred — a mask re-derives the
   * silhouette from a hand-kept SVG and drifts from the design.
   */
  shapeImageUrl?: string;
};
export type TimelineWidgetProps = {
  eyebrow: string;
  title: string;
  /** "muted" wraps the section in a soft rounded card (Mowing "Incentives"). */
  surface?: 'default' | 'muted';
  /**
   * "rows" is the default vertical-list rendering. "blobs" lays the entries
   * out as a row of organic coloured shapes (BioGarden "Projekt-Fahrplan").
   */
  variant?: 'rows' | 'blobs';
  /** Blobs variant: organic mask (SVG url) clipped over each blob. */
  blobMaskUrl?: string;
  /**
   * Blobs variant: organic mask for the marker tag. Set it and the marker
   * renders as a tilted blob overhanging the shape's top-left (the BioGarden
   * Figma); leave it blank and the marker stays the inline centered pill.
   */
  markerMaskUrl?: string;
  /** Supplied transparent artwork for the marker tag (replaces mask + colour). */
  markerImageUrl?: string;
  /** Blobs variant: CSS color filling the marker blob (Figma: brand yellow). */
  markerColor?: string;
  items: TimelineItem[];
};

/**
 * Marker-blob geometry, as fractions of the blob box, re-measured off the
 * BioGarden Figma (blob 415x343 at 59,4097; marker AABB 133.26x117.6 at
 * 48.88,**4094** — so the tag straddles the blob's upper-left edge, well clear
 * of the copy). The previous 27.4% top came from a mis-read y and dropped the
 * tag onto the entry title. The tag art is drawn tilted in the design and its
 * label stays upright, so the mask and the text are separate layers over one
 * shared centering box.
 */
export const MARKER_BLOB = {
  /** Center of the marker, relative to the blob box. */
  left: '13.6%',
  top: '16.3%',
  /** Unrotated width; the box keeps the tag vector's own aspect (no squash). */
  width: '27%',
  aspect: '159.547 / 116.348',
  rotation: '-20.12deg',
} as const;
