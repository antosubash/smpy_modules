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
  created_at: string;
  updated_at: string | null;
  /** Field key (or `"*"` for the whole type) -> ISO timestamp since a
   *  schema-affecting change enqueued a reindex that hasn't finished (design
   *  §8.5/§8.9). Non-empty while that field can't be filtered or sorted on. */
  reindex_pending: Record<string, string>;
};

/** The classification a schema-`fields` diff falls into (design §8.2). */
export type ChangeClass = 'additive' | 'index_affecting' | 'restrictive' | 'destructive';

/** One entry of a `SchemaPreview.changes` list — one line of "what changed
 *  on this field and how consequential it is". */
export type SchemaChange = {
  kind: ChangeClass;
  field_key: string;
  what: string;
  before: unknown;
  after: unknown;
};

/** One record the dry-run found would fail validation under the proposed
 *  schema. */
export type FailingRecord = {
  uuid: string;
  display_title: string;
  errors: { field: string; message: string }[];
};

/** The dry-run's report over a type's records against a proposed schema
 *  (design §8.9) — returned both by `POST .../schema/preview` and inline on
 *  a `409` from `PUT`/`.../restore` when a restrictive change would leave
 *  records invalid. */
export type DryRunReport = {
  checked: number;
  failing: number;
  sample: FailingRecord[];
  orphaned_conflicts: Record<string, number>;
  clean: boolean;
};

/** `POST /types/{key}/schema/preview`'s response: writes nothing, just
 *  classifies the proposed `fields` and dry-runs it. */
export type SchemaPreview = {
  kind: ChangeClass;
  changes: SchemaChange[];
  report: DryRunReport;
};

/** One snapshot of a type's schema, from `GET /types/{key}/revisions`. */
export type TypeRevision = {
  id: number;
  version: number;
  schema_version: number;
  fields: FieldDef[];
  display_field: string | null;
  slug_field: string | null;
  created_at: string;
  created_by: string | null;
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
  /** Empty when the record satisfies the current schema. Non-empty marks it
   *  "invalid under current schema" without hiding it (design §8.3) — set by
   *  a `force`d restrictive schema change or a schema rollback the record no
   *  longer fits. */
  invalid: { field: string; message: string }[];
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

/** `GET .../revisions/{id}`'s response — the list entry plus the payload it
 *  snapshotted, for the read-only preview before restoring it. */
export type RecordRevisionDetail = RecordRevision & { data: Record<string, unknown> };

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
  /** A restrictive schema change would leave records invalid — re-send with
   *  `force: true` (§8.2) or change the fields. */
  report?: DryRunReport;
  /** Re-adding a key that still holds `_orphaned` values on some records
   *  (§8.8) — re-send with `orphaned: 'restore' | 'discard'`. */
  conflicts?: Record<string, number>;
};
