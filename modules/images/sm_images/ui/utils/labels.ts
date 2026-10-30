import { codeMessage } from './api-net';
import { keys, type Translate } from './i18n';
import type { GalleryFilter, ImportKind, JobStatus, Visibility } from './types';

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

const JOB_STATUS = {
  uploading: keys.images.imports.status.uploading,
  pending: keys.images.imports.status.pending,
  staging: keys.images.imports.status.staging,
  running: keys.images.imports.status.running,
  paused: keys.images.imports.status.paused,
  resetting: keys.images.imports.status.resetting,
  completed: keys.images.imports.status.completed,
  failed: keys.images.imports.status.failed,
  cancelled: keys.images.imports.status.cancelled,
} satisfies Record<JobStatus, string>;

/** A job's status, or `stalled` for an active job whose runner went silent. */
export function jobStatusLabel(t: Translate, status: JobStatus, stalled = false): string {
  return t(stalled ? keys.images.imports.status.stalled : JOB_STATUS[status]);
}

const IMPORT_KIND = {
  geojson_url: keys.images.imports.kind.geojson_url,
  geojson_base64: keys.images.imports.kind.geojson_base64,
  zip: keys.images.imports.kind.zip,
} satisfies Record<ImportKind, string>;

export function importKindLabel(t: Translate, kind: ImportKind): string {
  return t(IMPORT_KIND[kind]);
}

/** The sentence for an error `code` of a step, an import job or a ZIP: its
 *  catalogue entry, `source_http_<status>` as the source's own answer, or the
 *  bare code for one this console has no words for yet. */
export function errorCodeLabel(t: Translate, code: string): string {
  const http = /^source_http_(\d{3})$/.exec(code);
  if (http) return t(keys.images.errors.source_http, { status: http[1] });
  return codeMessage(code) ?? code;
}
