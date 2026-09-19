/**
 * Wire types for the Records admin API and Inertia props.
 *
 * Mirrors `sm_records.contracts` (Python) field for field — see
 * `docs/plans/2026-09-19-records-module-design.md` §12 for the contract this
 * was built against. Kept in one file because every page and component needs
 * the same shapes; splitting it would just add import indirection.
 */

/** One typed field on a Record Type. `constraints`/`options` are per-`type`
 *  (e.g. `min`/`max` for `number`, `choices` for `select`) — opaque here
 *  because Phase 1 edits them as raw JSON, not through per-kind UI. */
export type FieldDef = {
  key: string;
  type: string;
  label: string;
  required: boolean;
  unique: boolean;
  indexed: boolean;
  default: unknown;
  help: string | null;
  constraints: Record<string, unknown>;
  options: Record<string, unknown>;
};

export type TypeRead = {
  key: string;
  label: string;
  label_plural: string;
  description: string | null;
  icon: string | null;
  fields: FieldDef[];
  schema_version: number;
  version: number;
  display_field: string | null;
  slug_field: string | null;
  is_public: boolean;
  allowed_roles: string[];
  record_count: number;
  trashed_record_count: number;
  fields_locked: boolean;
  created_at: string;
  updated_at: string | null;
};

export type RecordStatus = 'draft' | 'published';

export type RecordRead = {
  uuid: string;
  type_key: string;
  data: Record<string, unknown>;
  schema_stale: boolean;
  version: number;
  schema_version: number;
  status: RecordStatus;
  slug: string | null;
  display_title: string;
  position: number;
  published_at: string | null;
  created_at: string;
  updated_at: string | null;
  is_deleted: boolean;
};

export type RecordPage = {
  items: RecordRead[];
  total: number;
  page: number;
  page_size: number;
};

export type RecordRevision = {
  id: number;
  version: number;
  schema_version: number;
  event: string;
  display_title: string;
  created_at: string;
  created_by: string | null;
};

/** The filter grammar's operators (`?filter=field:op:value`). Mirrors
 *  `sm_records.index._predicates.FilterOp`. */
export type FilterOp = 'eq' | 'ne' | 'in' | 'contains' | 'gt' | 'gte' | 'lt' | 'lte' | 'is_null';

export const FILTER_OPS: FilterOp[] = [
  'eq',
  'ne',
  'contains',
  'gt',
  'gte',
  'lt',
  'lte',
  'in',
  'is_null',
];

/** A single `422` field error, as the API reports it. */
export type ValidationError = { field: string; message: string };

/** The union of error-response shapes the Records API sends on a non-2xx
 *  response. Every field is optional because which ones are present depends
 *  on the status code — a `409` on a type carries `current`, a bad filter
 *  carries `field`/`reason`, and so on (see the design doc's error table). */
export type ApiErrorBody = {
  detail?: string;
  errors?: ValidationError[];
  current?: RecordRead | TypeRead;
  referrers?: string[];
  field?: string;
  reason?: string;
};
