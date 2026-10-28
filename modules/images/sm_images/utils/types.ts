/** Wire shapes of `/api/images`, mirroring `sm_images/schemas`. */

export type Visibility = 'private' | 'internal' | 'public';

export type CollectionFilter = 'all' | 'owned' | 'shared' | 'internal' | 'public';

export type Collection = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  owner_id: string;
  visibility: Visibility;
  image_count: number;
  located_count: number;
  bbox: number[] | null;
  created_at: string | null;
  updated_at: string | null;
  is_owner: boolean;
};

export type Page<T> = {
  items: T[];
  next_cursor: string | null;
  /** Counted on the first page only. */
  total: number | null;
};

export type ImageItem = {
  id: string;
  collection_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  sha256: string | null;
  has_display: boolean;
  lat: number | null;
  lng: number | null;
  location_source: string | null;
  captured_at: string | null;
  camera_make: string | null;
  camera_model: string | null;
  external_source: string | null;
  external_id: string | null;
  properties: Record<string, unknown> | null;
  group_id: string | null;
  group_role: string | null;
  created_at: string | null;
  created_by: string | null;
  /** The versioned `small` rendition, or null until the pipeline made one. */
  thumb_url: string | null;
  /** The versioned display copy (the original's bytes when there is none). */
  display_url: string | null;
};

/** Gallery filter chips; each maps to query parameters of the list route. */
export type GalleryFilter = 'all' | 'located' | 'unlocated' | 'processing' | 'failed';

export type UploadResult = {
  filename: string | null;
  status: 'created' | 'duplicate' | 'error';
  id: string | null;
  code: string | null;
  detail: string | null;
};

export type ShareRole = 'view' | 'edit';

export type Share = {
  id: string;
  subject_id: string;
  subject_label: string | null;
  role: string;
  expired: boolean;
};

export type ShareCandidate = { id: string; display_name: string; email: string };

/** The `{detail, code}` envelope of an images error, or the framework's. */
export type ApiErrorBody = {
  detail?: unknown;
  code?: string;
  errors?: { field?: string; message: string }[];
};
