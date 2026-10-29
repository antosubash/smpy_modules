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
  /** A prompt step's prompt name (null for a built-in step or a deleted prompt). */
  label?: string | null;
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
  /** Detail response only: the key of the group `group_id` names. */
  group_key?: string | null;
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
  /** A prompt step's prompt name; absent for a built-in step. */
  label?: string | null;
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

// ---- Imports -------------------------------------------------------------

export type ImportKind = 'geojson_url' | 'geojson_base64' | 'zip';

export type JobStatus =
  | 'uploading'
  | 'pending'
  | 'staging'
  | 'running'
  | 'paused'
  | 'resetting'
  | 'completed'
  | 'failed'
  | 'cancelled';

/** The mapping the server takes (`sm_images.imports.mapping.Mapping`). */
export type ImportMapping = {
  url_prop?: string;
  image_prop?: string;
  lat_prop?: string;
  lng_prop?: string;
  datetime_prop?: string;
  external_id_prop?: string;
  group_key_prop?: string;
  group_role_prop?: string;
  filename_pattern?: string;
};

export type ImportJob = {
  id: string;
  collection_id: string;
  kind: ImportKind;
  status: JobStatus;
  mapping: ImportMapping;
  source_url: string | null;
  total_count: number;
  checkpoint_index: number;
  done_count: number;
  duplicate_count: number;
  failed_count: number;
  errors: ImportError[];
  auto_run_prompts: boolean;
  created_at: string;
  updated_at: string | null;
  heartbeat_at: string | null;
};

/** A job-level error, or a failed row's (`item` set; see `imports/item_errors.py`). */
export type ImportError = {
  code: string;
  at?: string;
  item?: number;
  status?: number;
  reason?: string;
  where?: string;
};

export type ImportControl = 'pause' | 'resume' | 'restart' | 'retry-failed';

export type GroupItem = {
  id: string;
  collection_id: string;
  key: string;
  name: string | null;
  description: string | null;
  image_count: number;
  /** In the collection's role order; the list carries the first few only. */
  members: ImageItem[];
};

/** What a regroup did; a big collection answers with a job (`RegroupJob`) instead. */
export type RegroupResult = {
  dry_run: boolean;
  scanned: number;
  matched: number;
  no_match: number;
  timed_out: number;
  already_grouped: number;
  unchanged: number;
  assigned: number;
  groups_created: number;
  groups_existing: number;
};

export type RegroupJob = RegroupResult & {
  id: string;
  collection_id: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  error_code: string | null;
  pattern: string;
  reassign: boolean;
  created_at: string | null;
  finished_at: string | null;
};
