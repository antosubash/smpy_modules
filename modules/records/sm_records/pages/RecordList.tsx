import { Head, usePage } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import type React from 'react';

import { ColumnChooser, ColumnsNotice } from '../components/ColumnChooser';
import { FilterBar } from '../components/FilterBar';
import { MediaApiProvider } from '../components/media/MediaApiContext';
import { displayedColumns } from '../components/RecordColumnCells';
import { RecordListActions } from '../components/RecordListActions';
import { RecordListBulk } from '../components/RecordListBulk';
import { RecordListEmpty } from '../components/RecordListEmpty';
import { RecordListFooter } from '../components/RecordListFooter';
import { RecordListPublicUrl } from '../components/RecordListPublicUrl';
import { RecordsToaster } from '../components/RecordsToaster';
import { RecordTable } from '../components/RecordTable';
import { useListColumns } from '../hooks/useListColumns';
import { useRecordListMutations } from '../hooks/useRecordListMutations';
import { useRecordListNav } from '../hooks/useRecordListNav';
import { useRecordSelection } from '../hooks/useRecordSelection';
import {
  exportSearchParams,
  filterErrorMessage,
  isCursorRefusal,
  parseFilterParam,
  parseSort,
  parseTrashedParam,
} from '../utils/listing';
import type { MediaApi } from '../utils/media-api';
import type { RecordListPage, TypeRead } from '../utils/types';

type Props = {
  type: TypeRead;
  records: RecordListPage;
  /** Every content locale the module runs (`views.py::record_list`); absent
   *  degrades to "no language UI", same as the editor's own prop. */
  content_locales?: string[];
  /** `RecordsSettings.max_import_bytes` — the import menu refuses a bigger
   *  file client-side and says the limit (R9/M13). Absent falls back to the
   *  setting's own default. */
  max_import_bytes?: number;
  /** `RecordsSettings.public_route_prefix` (U14/Missing-15) — shown, with a
   *  copy button, next to the type's label when `type.is_public` is on.
   *  Absent falls back to the same default the type editor's own
   *  `PublicField` uses. */
  public_route_prefix?: string;
  /** Where a `media` column resolves its thumbnails; `null` shows the id. */
  media_api?: MediaApi | null;
};
/** The permission the "Trash" toggle costs — see `deps.py::parse_trashed`. */
const EDIT_PERMISSION = 'records.edit';

/** `Records/RecordList` — `/admin/records/{key}`. A generic table over one
 *  type's records, driven entirely by the URL (`?page=` or `?after=`,
 *  `filter=`/`sort=`, and the client-only `?columns=`) so it can be
 *  bookmarked or shared. */
function RecordList({
  type,
  records,
  content_locales,
  max_import_bytes,
  public_route_prefix,
  media_api,
}: Props) {
  const { t } = useT();
  const page = usePage<{ errors?: Record<string, string>; auth?: SharedProps['auth'] }>();
  const search = new URL(page.url, window.location.origin).searchParams;
  const rawFilter = search.get('filter');
  // A cursor lives in the URL and nowhere else (`utils/listing.ts::listParams`).
  const after = search.get('after');
  const trashed = parseTrashedParam(search.get('trashed'));
  const canEdit = page.props.auth?.permissions?.includes(EDIT_PERMISSION) ?? false;
  const rawPageSize = Number(search.get('page_size')) || records.page_size;
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
  // A refused *cursor* arrives on the same channel, but the filter was fine:
  // Export and the bulk toolbar keep it, and the empty box offers page 1.
  const cursorRefused = isCursorRefusal(filterErrorReason);
  const filterRefused = Boolean(filterErrorReason) && !cursorRefused;
  // `columns` is the list's own display choice, not a query the export
  // understands: an export is always the full row.
  const exportParams = new URLSearchParams(search);
  exportParams.delete('columns');
  const exportSearch = exportSearchParams(exportParams.toString(), filterRefused);

  const { listTop, loading, current, goTo, applyFilter, clearFilter, handleSort, toggleTrashed } =
    useRecordListNav({
      typeKey: type.key,
      page: records.page,
      after,
      filters: search.getAll('filter'),
      sorts: search.getAll('sort'),
      trashed,
      rawPageSize,
      currentSort,
      rawColumns: search.get('columns'),
    });
  const columns = useListColumns({
    type,
    showLocale: showLocaleUI,
    current,
    currentSort,
    goTo,
  });

  const { handleDelete, handleRestore, handlePurge } = useRecordListMutations(type.key, t);
  // Only the rows this page is showing — see `useRecordSelection`.
  const selection = useRecordSelection(records.items.map((record) => record.uuid));

  // `total` is exact only up to `RecordsSettings.max_count` (F4): beyond it
  // the API reports the cap with `total_capped`, and the footer says
  // "10,000+" rather than a number that is not the number. The numbered
  // pager reads the same capped value, so it pages to the cap; past it the
  // footer follows `next_cursor` (`RecordPagination`).
  const known = records.total ?? 0;
  // U30: nothing to filter — no filter active, not viewing the trash, not
  // past the numbered pages, and this render's own result is empty, which
  // then means the type has no records at all (not merely none here).
  const genuinelyEmpty =
    records.items.length === 0 && !trashed && !currentFilter && !filterErrorReason && !after;

  return (
    <>
      <Head title={type.label_plural} />
      <PageShell
        title={type.label_plural}
        description={type.description ?? undefined}
        actions={
          <RecordListActions
            typeKey={type.key}
            fields={type.fields}
            canEdit={canEdit}
            trashed={trashed}
            exportSearch={exportSearch}
            filtered={Boolean(currentFilter) && !filterRefused}
            recordCount={known}
            maxImportBytes={max_import_bytes}
            onToggleTrashed={toggleTrashed}
            columnsMenu={
              // `genuinelyEmpty` is false on a cursor page, so an empty or
              // refused cursor page keeps the chooser (and the filter bar).
              !genuinelyEmpty && (
                <ColumnChooser
                  available={columns.available}
                  // What the table shows, so the panel's ticks match the
                  // screen (the default view's all-zero Position included).
                  resolved={{
                    ...columns.resolved,
                    columns: displayedColumns(columns.resolved, records.items),
                  }}
                  onChange={columns.change}
                  onReset={columns.reset}
                />
              )
            }
          />
        }
      >
        {type.is_public && (
          <RecordListPublicUrl typeKey={type.key} publicRoutePrefix={public_route_prefix} />
        )}
        {/* Contains the list's own overflow (UX-R4): the table already
            scrolls inside its own box, and nothing else here may push the
            document sideways on a phone. */}
        <div className="min-w-0 overflow-x-clip">
          {/* U30: a brand-new, unfiltered, non-trashed type with zero
              records has nothing to filter — the full Field/Condition/
              Value/Apply bar above an empty box read as chrome for a
              feature the screen could not use yet. Any filter, the trash
              toggle, or a single record brings it straight back. */}
          {!genuinelyEmpty && (
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
          )}

          <ColumnsNotice resolved={columns.resolved} />

          {filterErrorReason && (
            <div
              data-testid="records-filter-error"
              className="mb-4 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm"
            >
              {filterErrorMessage(t, filterErrorReason)}
            </div>
          )}

          <div
            ref={listTop}
            className={
              loading
                ? 'scroll-mt-4 opacity-60 transition-opacity pointer-events-none'
                : 'scroll-mt-4 transition-opacity'
            }
            aria-busy={loading}
            data-testid="records-list-wrapper"
          >
            {canEdit && (
              <RecordListBulk
                typeKey={type.key}
                trashed={trashed}
                records={records.items}
                selection={selection}
                filters={filterRefused ? [] : search.getAll('filter')}
                total={known}
                capped={records.total_capped}
              />
            )}
            {records.items.length === 0 ? (
              <RecordListEmpty
                typeKey={type.key}
                trashed={trashed}
                filtered={Boolean(currentFilter) || Boolean(filterErrorReason)}
                errorMessage={filterErrorReason ? filterErrorMessage(t, filterErrorReason) : null}
                canImport={canEdit}
                cursor={after ? (cursorRefused ? 'refused' : 'ended') : null}
                onClear={clearFilter}
                onFirstPage={() => goTo({ page: 1 })}
              />
            ) : (
              <MediaApiProvider value={media_api}>
                <RecordTable
                  type={type}
                  records={records.items}
                  sort={currentSort}
                  trashed={trashed}
                  selection={canEdit ? selection : undefined}
                  showLocale={showLocaleUI}
                  columns={columns.resolved}
                  onSort={handleSort}
                  onDelete={handleDelete}
                  onRestore={handleRestore}
                  onPurge={handlePurge}
                />
              </MediaApiProvider>
            )}
          </div>

          <RecordListFooter
            records={records}
            total={known}
            errorReason={filterErrorReason}
            loading={loading}
            goTo={goTo}
          />
        </div>
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
