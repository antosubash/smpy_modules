/**
 * Wire types for the Records admin API and Inertia props: Record Type
 * shapes (the schema side).
 *
 * Mirrors `sm_records.contracts` (Python) field for field — see
 * `docs/plans/2026-09-19-records-module-design.md` §12 for the contract this
 * was built against. Record-instance shapes (`RecordRead` and friends) live
 * in `utils/record-types.ts`, re-exported from here so every existing
 * `from '.../utils/types'` import keeps working — split out once adding
 * `TypeRead.show_in_menu` pushed this file over the 300-line cap.
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
  /** Which table set this type's documents live in (Phase 5 §6.2), or `null`
   *  for the shared ones. Set once, at creation: the API answers a `PUT`
   *  that changes it with a 409, so the editor shows it read-only. */
  collection: string | null;
  record_count: number;
  trashed_record_count: number;
  /** Live records carrying a stored invalid mark — what a forced schema
   *  change left behind (design §8.3). A subset of `record_count`, and the
   *  number the hub row shows beside a link that filters the list by
   *  `invalid:eq:true`. */
  invalid_record_count: number;
  created_at: string;
  updated_at: string | null;
  /** Field key (or `"*"` for the whole type) -> ISO timestamp since a
   *  schema-affecting change enqueued a reindex that hasn't finished (design
   *  §8.5/§8.9). Non-empty while that field can't be filtered or sorted on. */
  reindex_pending: Record<string, string>;
  /** Whether this type's records may be authored in more than one content
   *  locale (Phase 5 §4.1). Off by default — a type that is not translatable
   *  has every record in the default content locale and shows no language UI.
   *  Turning it off while records in another locale exist is refused (409). */
  translatable: boolean;
  /** Whether this type has its own admin sidebar entry, next to the
   *  "Records" hub (per-type sidebar entries design contract). Off by
   *  default. */
  show_in_menu: boolean;
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

/** `POST .../schema/preview`'s 202 body: the dry run was too big to run
 *  inside the request (F10), so it runs deferred and this is its handle. */
export type SchemaPreviewStarted = { job: string; status: string };

/** `GET .../schema/preview/{job}` — the deferred dry run's state. `preview`
 *  is the same shape the synchronous path returns, present once `status` is
 *  `"done"`. */
export type SchemaPreviewJob = {
  job: string;
  status: 'running' | 'done' | 'failed';
  checked: number;
  total: number;
  preview: SchemaPreview | null;
  error: string | null;
};

/** One page of `GET /types/{key}/revisions`.
 *
 * Paged because type revisions are never pruned — they are what a rollback
 * reads — so the response grew for the lifetime of the type and was
 * re-downloaded on every open of the schema screen. `total` is exact.
 */
export type TypeRevisionPage = {
  items: TypeRevision[];
  total: number;
  page: number;
  page_size: number;
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

// Record-instance shapes (RecordRead, RecordPage, ValidationError, FilterOp,
// ApiErrorBody, ...) live in `utils/record-types.ts` — re-exported below so
// every existing import site is unaffected.
export * from './record-types';
