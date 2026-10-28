import { keys, type Translate } from './i18n';
import type { GalleryFilter, Visibility } from './types';

/** Choices whose labels are looked up at render time are a `Record` of `keys.…`
 *  leaves, not a template literal, so `tsc` still checks every key. */
const VISIBILITY = {
  private: keys.images.visibility.private,
  internal: keys.images.visibility.internal,
  public: keys.images.visibility.public,
} satisfies Record<Visibility, string>;

export function visibilityLabel(t: Translate, visibility: Visibility): string {
  return t(VISIBILITY[visibility]);
}

export const VISIBILITIES: Visibility[] = ['private', 'internal', 'public'];

const GALLERY_FILTER = {
  all: keys.images.gallery.filter.all,
  located: keys.images.gallery.filter.located,
  unlocated: keys.images.gallery.filter.unlocated,
  processing: keys.images.gallery.filter.processing,
  failed: keys.images.gallery.filter.failed,
} satisfies Record<GalleryFilter, string>;

export const GALLERY_FILTERS = Object.keys(GALLERY_FILTER) as GalleryFilter[];

export function galleryFilterLabel(t: Translate, filter: GalleryFilter): string {
  return t(GALLERY_FILTER[filter]);
}

const COLLECTION_FILTER = {
  all: keys.images.collections.filter.all,
  owned: keys.images.collections.filter.owned,
  shared: keys.images.collections.filter.shared,
  internal: keys.images.collections.filter.internal,
  public: keys.images.collections.filter.public,
} as const;

export const COLLECTION_FILTERS = Object.keys(
  COLLECTION_FILTER,
) as (keyof typeof COLLECTION_FILTER)[];

export function collectionFilterLabel(
  t: Translate,
  filter: keyof typeof COLLECTION_FILTER,
): string {
  return t(COLLECTION_FILTER[filter]);
}
