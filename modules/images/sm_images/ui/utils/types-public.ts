/** Wire shapes of the anonymous surface, `/api/images/public/c/{slug}`. */

/** One tile of a public collection (`…/images`): ids and anonymous URLs only,
 *  never a filename or metadata. */
export type PublicImage = {
  id: string;
  width: number | null;
  height: number | null;
  thumb_url: string;
  display_url: string;
};

export type PublicPage = {
  items: PublicImage[];
  next_cursor: string | null;
};

/** What the public page (`Images/PublicCollection`) is told about its collection. */
export type PublicCollectionInfo = {
  slug: string;
  name: string;
  description: string | null;
  image_count: number;
  located_count: number;
  bbox: number[] | null;
};

/** A GeoJSON point of `…/points`: the id, nothing about the picture. */
export type PointFeature = {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number, number] };
  properties: { id: string; captured_at: string | null; group_id: string | null };
};

export type PointsPage = {
  type: 'FeatureCollection';
  features: PointFeature[];
  next_cursor: string | null;
};
