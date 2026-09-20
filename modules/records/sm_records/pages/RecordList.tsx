import { Head, Link, router, usePage } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import type React from 'react';

import { FilterBar, type FilterValue } from '../components/FilterBar';
import { RecordIoMenu } from '../components/RecordIoMenu';
import { RecordPagination } from '../components/RecordPagination';
import { RecordsToaster } from '../components/RecordsToaster';
import { RecordTable } from '../components/RecordTable';
import { deleteRecord, restoreRecord } from '../utils/api-records';
import { buildSortParam, filterErrorReasonKey, nextSort, parseSort } from '../utils/listing';
import type { FilterOp, RecordPage, RecordRead, TypeRead } from '../utils/types';

type Props = {
  type: TypeRead;
  records: RecordPage;
  /** Every content locale the module runs (`views.py::record_list`); absent
   *  degrades to "no language UI", same as the editor's own prop. */
  content_locales?: string[];
};
/** The permission the "Trash" toggle costs — see `deps.py::parse_trashed`. */
const EDIT_PERMISSION = 'records.edit';

// See `FilterBar.tsx` for why `t` is typed this loosely here: typing it
// against `useT()`'s real, key-union-overloaded signature either blows up TS
// with an "excessively deep" instantiation or fails to unify when called.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

/** One term of the filter/sort grammar failed to build into a query —
 *  `filterErrorReasonKey` narrows `reason` to the closed set this maps.
 *  Every branch keeps its own literal `t()` call (rather than a
 *  `Record<FilterErrorReason, string>` built once) for the same reason
 *  `FilterBar`'s `opLabel` does: `make ci-check-untranslated` can't see
 *  through a config object, only a call it can find. */
function filterErrorMessage(t: Translate, reason: string | undefined): string {
  switch (filterErrorReasonKey(reason)) {
    case 'reindexing':
      return t('records.list.filter_error.reindexing', {
        defaultValue:
          'That field is being reindexed right now and cannot be filtered on yet. Try again shortly.',
      });
    case 'unsupported_op':
      return t('records.list.filter_error.unsupported_op', {
        defaultValue: "That condition isn't supported for this field.",
      });
    case 'not_indexed':
      return t('records.list.filter_error.not_indexed', {
        defaultValue: "That field isn't indexed, so it can't be filtered or sorted on.",
      });
    case 'unknown':
      return t('records.list.filter_error.unknown', {
        defaultValue: "That field doesn't exist on this record type.",
      });
    case 'bad_value':
      return t('records.list.filter_error.bad_value', {
        defaultValue: "That value isn't valid for this field.",
      });
    default:
      return t('records.list.filter_error.generic', {
        defaultValue: "That filter couldn't be applied.",
      });
  }
}

/** Split on the first two colons — the value half of `field:op:value` may
 *  itself contain one (an ISO datetime), and the field/op halves never do. */
function parseFilterParam(raw: string | null): FilterValue {
  if (!raw) return null;
  const first = raw.indexOf(':');
  const second = raw.indexOf(':', first + 1);
  if (first < 0 || second < 0) return null;
  return {
    field: raw.slice(0, first),
    op: raw.slice(first + 1, second) as FilterOp,
    value: raw.slice(second + 1),
  };
}

/** `Records/RecordList` — `/admin/records/{key}`. A generic table over one
 *  type's records, driven entirely by the URL (`?page=&filter=&sort=`) so it
 *  can be bookmarked or shared. */
function RecordList({ type, records, content_locales }: Props) {
  const { t } = useT();
  const page = usePage<{ errors?: Record<string, string>; auth?: SharedProps['auth'] }>();
  const search = new URL(page.url, window.location.origin).searchParams;
  const rawFilter = search.get('filter');
  const rawSort = search.get('sort');
  const trashed = search.get('trashed') === 'true';
  const canEdit = page.props.auth?.permissions?.includes(EDIT_PERMISSION) ?? false;
  const currentFilter = parseFilterParam(rawFilter);
  const currentSort = parseSort(search.toString());
  // The admin list always defaults to every locale (design §4.4) — the
  // column and filter only earn their place once the type actually uses more
  // than one, so a monolingual type or install shows neither.
  const contentLocales = content_locales ?? [];
  const showLocaleUI = type.translatable && contentLocales.length > 1;
  // Inertia's own `errors` bag — `record_list` (views.py) attaches
  // `{filter: exc.reason}` whenever building the query raises `QueryError`,
  // regardless of whether the offending term came from `?filter=` or
  // `?sort=` — both are resolved through the same index-lookup call, so a
  // sort on a field that's mid-reindex (design doc §8.5) lands on this same
  // channel under the same "filter" key rather than failing the navigation
  // outright. This is shown for *any* reason `QueryError` carries (F1), not
  // only `reindexing`: `unsupported_op` (an operator this build stopped
  // offering, or a hand-edited URL), `not_indexed`, `unknown` and
  // `bad_value` all land here too, and without a message the list rendered
  // identically to a type with no matching records — indistinguishable from
  // an actually-empty result. A sort on an *unindexed* field would land here
  // as well, but `SortableHeader` never offers one, so that branch shouldn't
  // be reachable from this UI short of a hand-edited URL.
  const filterErrorReason = page.props.errors?.filter;

  const goTo = (next: {
    page?: number;
    filter?: string | null;
    sort?: string | null;
    trashed?: boolean;
  }) => {
    const params: Record<string, string> = {};
    const targetPage = next.page ?? records.page;
    if (targetPage > 1) params.page = String(targetPage);
    const targetFilter = next.filter === undefined ? rawFilter : next.filter;
    if (targetFilter) params.filter = targetFilter;
    const targetSort = next.sort === undefined ? rawSort : next.sort;
    if (targetSort) params.sort = targetSort;
    const targetTrashed = next.trashed ?? trashed;
    if (targetTrashed) params.trashed = 'true';
    // Toggling `trashed` swaps every prop (`records`, `errors` and, via
    // `parse_trashed`, what the server even lets through) — a partial reload
    // only makes sense for staying inside the same trashed/live view.
    const full = next.trashed !== undefined;
    router.get(`/admin/records/${type.key}`, params, {
      only: full ? undefined : ['records', 'errors'],
      preserveState: true,
      preserveScroll: true,
      replace: true,
    });
  };

  const applyFilter = (field: string, op: FilterOp, value: string) =>
    goTo({ page: 1, filter: `${field}:${op}:${value}` });
  const clearFilter = () => goTo({ page: 1, filter: null });
  const handleSort = (field: string) =>
    goTo({ page: 1, sort: buildSortParam(nextSort(currentSort, field)) ?? null });
  const toggleTrashed = () => goTo({ page: 1, trashed: !trashed });

  const handleDelete = async (record: RecordRead) => {
    await deleteRecord(type.key, record.uuid);
    router.reload({ only: ['records'] });
  };

  const handleRestore = async (record: RecordRead) => {
    await restoreRecord(type.key, record.uuid);
    router.reload({ only: ['records'] });
  };

  // `total` is exact only up to `RecordsSettings.max_count` (F4): beyond it
  // the API reports the cap with `total_capped`, and the footer says
  // "10,000+" rather than a number that is not the number. Everything that
  // uses it for arithmetic — the range, and whether there is a next page —
  // reads the same capped value, so a capped listing simply pages to the cap
  // and the cursor contract (`next_cursor`) is what an API client walks past
  // it with.
  const known = records.total ?? 0;

  return (
    <>
      <Head title={type.label_plural} />
      <PageShell
        title={type.label_plural}
        description={type.description ?? undefined}
        actions={
          <>
            <Button variant="outline" onClick={() => router.visit('/admin/records')}>
              {t('records.types.title', { defaultValue: 'Record Types' })}
            </Button>
            {/* `search` and not `''`: "Export" means "export what this screen
                is showing", so the current `filter`/`sort`/`trashed` travel
                with it — `exportUrl` drops only `page`. */}
            <RecordIoMenu
              typeKey={type.key}
              search={search.toString()}
              canEdit={canEdit}
              fields={type.fields}
              trashed={trashed}
            />
            {canEdit && (
              <Button
                type="button"
                variant={trashed ? 'default' : 'outline'}
                data-testid="records-trash-toggle"
                onClick={toggleTrashed}
              >
                {trashed
                  ? t('records.trash.view_live', { defaultValue: 'Back to live records' })
                  : t('records.trash.view', { defaultValue: 'Trash' })}
              </Button>
            )}
            {!trashed && (
              <Button asChild>
                <Link href={`/admin/records/${type.key}/new`}>
                  {t('records.records.new', { defaultValue: 'New record' })}
                </Link>
              </Button>
            )}
          </>
        }
      >
        <div className="mb-4">
          <FilterBar
            key={rawFilter ?? '__none__'}
            fields={type.fields}
            current={currentFilter}
            onApply={applyFilter}
            onClear={clearFilter}
            locales={showLocaleUI ? contentLocales : []}
          />
        </div>

        {filterErrorReason && (
          <div
            data-testid="records-filter-error"
            className="mb-4 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm"
          >
            {filterErrorMessage(t, filterErrorReason)}
          </div>
        )}

        {records.items.length === 0 ? (
          <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
            {trashed
              ? t('records.trash.empty', { defaultValue: 'No trashed records' })
              : t('records.records.empty', { defaultValue: 'No records yet' })}
          </div>
        ) : (
          <RecordTable
            type={type}
            records={records.items}
            sort={currentSort}
            trashed={trashed}
            showLocale={showLocaleUI}
            onSort={handleSort}
            onDelete={handleDelete}
            onRestore={handleRestore}
          />
        )}

        <RecordPagination
          page={records.page}
          pageSize={records.page_size}
          total={known}
          capped={records.total_capped}
          itemCount={records.items.length}
          onGo={(next) => goTo({ page: next })}
        />
      </PageShell>
    </>
  );
}

RecordList.layout = (page: React.ReactNode) => (
  <AdminLayout>
    {page}
    <RecordsToaster />
  </AdminLayout>
);
export default RecordList;
