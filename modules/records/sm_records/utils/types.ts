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
  /** Which table set this type's documents live in (Phase 5 §6.2), or `null`
   *  for the shared ones. Set once, at creation: the API answers a `PUT`
   *  that changes it with a 409, so the editor shows it read-only. */
  collection: string | null;
  record_count: number;
  trashed_record_count: number;
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

/** One sibling in a record's translation group, as `GET
 *  .../records/{uuid}/translations` lists it and as `RecordRead.translations`
 *  embeds it (design §4.4). Mirrors `contracts/i18n.py::TranslationRead`. */
export type TranslationRead = {
  locale: string;
  uuid: string;
  status: RecordStatus;
  display_title: string;
  /** A trashed sibling is still a sibling: it keeps its slug claim in its
   *  locale, so the Languages panel shows it rather than offering to create
   *  a second translation that would then collide. */
  is_deleted: boolean;
};

/** One stored relation reference, resolved under `?expand=` (design §9).
 *  Mirrors `contracts/relations.py::ExpandedRef` — exactly one of the three
 *  states holds: resolved (`display_title` set), `dangling` (target trashed
 *  or gone) or `restricted` (target's type narrows `allowed_roles` past the
 *  caller). */
export type ExpandedRef = {
  type_key: string;
  uuid: string;
  display_title: string | null;
  slug: string | null;
  status: string | null;
  dangling: boolean;
  restricted: boolean;
};

/** One record pointing at the record being read, and what deleting the
 *  target would do to it — mirrors `contracts/relations.py::ReferrerRead`. */
export type ReferrerRead = {
  type_key: string;
  type_label: string;
  uuid: string;
  display_title: string;
  field_key: string;
  field_label: string;
  on_delete: string;
  is_deleted: boolean;
};

/** `GET .../records/{uuid}/referrers`'s response. `total` counts every
 *  *distinct referring record* — live and trashed, including ones this
 *  caller may not view (a record referencing via two fields counts once).
 *  `hidden` is how many of those `total` this caller may not view; `items`
 *  (capped by page size) is paginated over the visible ones only, so
 *  `items.length` across every page sums to `total - hidden` (design
 *  §9/§10). */
export type ReferrersResponse = {
  items: ReferrerRead[];
  total: number;
  hidden: number;
};

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
  /** The record's language, fixed for its lifetime (design §4.3) — set at
   *  create and never changed by an update. */
  locale: string;
  /** What this record and its translations share; a record with no siblings
   *  is alone in its own group. */
  translation_group: string;
  /** Empty when the record satisfies the current schema. Non-empty marks it
   *  "invalid under current schema" without hiding it (design §8.3) — set by
   *  a `force`d restrictive schema change or a schema rollback the record no
   *  longer fits. */
  invalid: { field: string; message: string }[];
  /** Relation targets resolved under an explicit `?expand=a,b` (design §9):
   *  field key -> one `ExpandedRef` per stored reference, in payload order.
   *  `undefined`/`null` when the caller did not ask (a plain list row, or a
   *  record freshly returned by a create/update, which does not expand). */
  expanded?: Record<string, ExpandedRef[]> | null;
  /** The record's siblings, one entry per other content locale it exists in
   *  — present under `?translations=true` and on the editor view, `undefined`
   *  everywhere else (never on the list, design §4.4). */
  translations?: TranslationRead[] | null;
};

export type RecordPage = {
  items: RecordRead[];
  /** Exact up to `RecordsSettings.max_count`, `null` when the caller sent
   *  `?total=false` (F4). */
  total: number | null;
  /** The real number is larger than `total` — the list shows "10,000+". */
  total_capped: boolean;
  page: number;
  page_size: number;
  /** The opaque `?after=` value for the page after this one, `null` on the
   *  last page (F11). The admin UI pages by number and ignores it; an API
   *  client walking the type should use it instead of `?page=`. */
  next_cursor: string | null;
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
export type FilterOp =
  | 'eq'
  | 'ne'
  | 'in'
  | 'contains'
  | 'starts_with'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'is_null';

export const FILTER_OPS: FilterOp[] = [
  'eq',
  'ne',
  'contains',
  'starts_with',
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
  /** A `409` on delete: visible referrers (capped), plus `hidden`/`more`. */
  referrers?: string[];
  hidden?: number;
  more?: number;
  field?: string;
  reason?: string;
  /** A restrictive schema change would leave records invalid — re-send with
   *  `force: true` (§8.2) or change the fields. */
  report?: DryRunReport;
  /** Re-adding a key that still holds `_orphaned` values on some records
   *  (§8.8) — re-send with `orphaned: 'restore' | 'discard'`. */
  conflicts?: Record<string, number>;
};
