/**
 * Wire types for the Records admin API: record-instance shapes.
 *
 * Split out of `utils/types.ts` — which mirrors `sm_records.contracts`
 * (Python) field for field, see
 * `docs/plans/2026-09-19-records-module-design.md` §12 for the contract this
 * was built against — once adding `TypeRead.show_in_menu` pushed that file
 * over the 300-line cap. `utils/types.ts` re-exports everything here, so
 * every existing `from '.../utils/types'` import is unaffected; this file
 * exists purely to keep both under the cap, not as a boundary callers need
 * to know about.
 */

import type { DryRunReport, TypeRead } from './types';

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

/**
 * U20: the Languages panel is a page prop (`views.py::record_edit`'s
 * `translations`), fetched once at load — a save that changes the title
 * updates `current` (`useRecordEditor.ts`) but left this list showing what
 * was true when the page opened, so after saving "Herbstgipfel" the h1
 * updated and the panel kept reading "Autumn Summit" for the very record
 * being edited.
 *
 * Patches the entry whose `locale` matches `current`'s from `current`
 * itself, rather than refetching — `current` already *is* the freshest copy
 * of that sibling. Every other locale's entry is untouched: this component
 * has no fresher data about them than the page load gave it.
 */
export function withCurrentPatched(
  translations: readonly TranslationRead[],
  current: Pick<
    TranslationRead,
    'locale' | 'uuid' | 'status' | 'display_title' | 'is_deleted'
  > | null,
): TranslationRead[] {
  if (!current) return [...translations];
  return translations.map((sibling) =>
    sibling.locale === current.locale
      ? {
          ...sibling,
          uuid: current.uuid,
          status: current.status,
          display_title: current.display_title,
          is_deleted: current.is_deleted,
        }
      : sibling,
  );
}

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
  /** When a scan last found this record wanting, or `null` — the *stored*
   *  mark (`services/_invalid.py`), and unlike `invalid` it is filled on a
   *  list row too. The list is where it matters: `invalid` is empty there by
   *  construction, because filling it would cost a validator pass per row.
   *  Written by a forced schema change or a rescan, cleared by the record's
   *  next successful save. */
  invalid_since: string | null;
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
   *  last page (F11). An API client walking the type should use it instead
   *  of `?page=`; the admin list follows it past the capped count. */
  next_cursor: string | null;
};

/** `RecordPage` as the list screen receives it (`endpoints/_list_view.py`'s
 *  `RecordListViewPage`): `page` is `null` on a page reached by `?after=`,
 *  which is past the numbered pages and has no number. */
export type RecordListPage = Omit<RecordPage, 'page'> & { page: number | null };

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

/** The `report` a refused `POST …/records/bulk` carries: which records said
 *  no, and what each of them alone would have answered. Nothing was written.
 *  Mirrored in `utils/api-records.ts` as `BulkReport`, which is what callers
 *  use; declared here because `ApiErrorBody` cannot import from a module that
 *  imports it. */
export type BulkReportBody = {
  action: string;
  requested: number;
  failed: { uuid: string; status: number; message: string }[];
};

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
  /** Two refusals ride on one key, told apart by their shape and by the
   *  route that answered: a restrictive schema change that would leave
   *  records invalid — re-send with `force: true` (§8.2) or change the
   *  fields — and a bulk action at least one named record refused, which is
   *  the one with `failed` on it. */
  report?: DryRunReport | BulkReportBody;
  /** Re-adding a key that still holds `_orphaned` values on some records
   *  (§8.8) — re-send with `orphaned: 'restore' | 'discard'`. */
  conflicts?: Record<string, number>;
};
