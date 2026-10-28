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

/** One step's state for one image. Only the detail response carries these; for
 *  someone who may not edit, only `step`, `status` and `error_code` are set. */
export type StepRun = {
  step: string;
  status: string;
  step_version: number | null;
  error_code: string | null;
  error_message: string | null;
  finished_at: string | null;
  output: Record<string, unknown> | null;
  /** True for an editor: `output === null` then means the step made none. */
  output_visible?: boolean;
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
  /** Detail response only. */
  step_runs?: StepRun[] | null;
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

// ---- Pipeline ------------------------------------------------------------

/** A JSON Schema as pydantic emits it; only the parts the params form reads. */
export type JsonSchema = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  anyOf?: JsonSchema[];
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  required?: string[];
};

export type PipelineStep = {
  id: string;
  installed: boolean;
  state: string;
  enabled: boolean;
  params?: Record<string, unknown>;
  version?: number;
  queue?: string;
  requires?: string[];
  mutates_display?: boolean;
  params_schema?: JsonSchema;
};

export type PipelineOverview = {
  config: { steps: Record<string, Record<string, unknown>> };
  preset_id: string | null;
  steps: PipelineStep[];
  status: Record<string, Record<string, number>>;
  stale: number;
  not_installed: number;
  pending: number;
};

export type RestartScope = 'failed' | 'stale' | 'all';
