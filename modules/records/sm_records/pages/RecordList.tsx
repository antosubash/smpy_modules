import { Head, Link, router, usePage } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import type React from 'react';

import { FilterBar } from '../components/FilterBar';
import { RecordIoMenu } from '../components/RecordIoMenu';
import { RecordListEmpty } from '../components/RecordListEmpty';
import { RecordListPublicUrl } from '../components/RecordListPublicUrl';
import { RecordPagination } from '../components/RecordPagination';
import { RecordsToaster } from '../components/RecordsToaster';
import { RecordTable } from '../components/RecordTable';
import { useRecordListMutations } from '../hooks/useRecordListMutations';
import { useRecordListNav } from '../hooks/useRecordListNav';
import {
  exportSearchParams,
  filterErrorMessage,
  listStatus,
  parseFilterParam,
  parseSort,
  parseTrashedParam,
} from '../utils/listing';
import type { RecordPage, TypeRead } from '../utils/types';

type Props = {
  type: TypeRead;
  records: RecordPage;
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
};
/** The permission the "Trash" toggle costs — see `deps.py::parse_trashed`. */
const EDIT_PERMISSION = 'records.edit';

/** `Records/RecordList` — `/admin/records/{key}`. A generic table over one
 *  type's records, driven entirely by the URL (`?page=&filter=&sort=`) so it
 *  can be bookmarked or shared. */
function RecordList({
  type,
  records,
  content_locales,
  max_import_bytes,
  public_route_prefix,
}: Props) {
  const { t } = useT();
  const page = usePage<{ errors?: Record<string, string>; auth?: SharedProps['auth'] }>();
  const search = new URL(page.url, window.location.origin).searchParams;
  const rawFilter = search.get('filter');
  const rawSort = search.get('sort');
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
  const exportSearch = exportSearchParams(search.toString(), Boolean(filterErrorReason));

  const { listTop, loading, goTo, applyFilter, clearFilter, handleSort, toggleTrashed } =
    useRecordListNav({
      typeKey: type.key,
      page: records.page,
      rawFilter,
      rawSort,
      trashed,
      rawPageSize,
      currentSort,
    });

  const { handleDelete, handleRestore, handlePurge } = useRecordListMutations(type.key, t);

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
          // `PageShell` lays its own `actions` row out `flex-shrink-0` with
          // no wrapping (it lives in the framework's `@simple-module-py/ui`
          // package, which this module cannot change), so four buttons ran
          // straight off a 390px document and took the whole page's
          // horizontal scroll with them (UX-R4). Below `sm` that row is a
          // full-width column item, so a wrapping flex row inside it is the
          // fix from this side of the boundary.
          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            <Button variant="outline" onClick={() => router.visit('/admin/records')}>
              {t('records.types.title', { defaultValue: 'Record Types' })}
            </Button>
            {/* `search` and not `''`: "Export" means "export what this screen
                is showing", so the current `filter`/`sort`/`trashed` travel
                with it — `exportUrl` drops only `page`, and `exportSearch`
                drops a `filter` the list is already showing an error for
                (polish note: that download is a raw JSON 400 in a new tab). */}
            <RecordIoMenu
              typeKey={type.key}
              search={exportSearch}
              canEdit={canEdit}
              fields={type.fields}
              trashed={trashed}
              {...(max_import_bytes ? { maxImportBytes: max_import_bytes } : {})}
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
          </div>
        }
      >
        {type.is_public && (
          <RecordListPublicUrl typeKey={type.key} publicRoutePrefix={public_route_prefix} />
        )}
        {/* Contains the list's own overflow (UX-R4): the table already
            scrolls inside its own box, and nothing else here may push the
            document sideways on a phone. */}
        <div className="min-w-0 overflow-x-clip">
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
            {records.items.length === 0 ? (
              <RecordListEmpty
                typeKey={type.key}
                trashed={trashed}
                filtered={Boolean(currentFilter) || Boolean(filterErrorReason)}
                errorMessage={filterErrorReason ? filterErrorMessage(t, filterErrorReason) : null}
                onClear={clearFilter}
              />
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
                onPurge={handlePurge}
              />
            )}
          </div>

          {/* A filter, a sort or a page swaps the rows through a partial
            reload with no focus move, so a screen reader was never told the
            page had become a different page (UX-R15). U10: a refused filter
            used to announce "0 records, page 1 of 1" here — an assertion
            about data that was never queried — while a sighted user read the
            real reason in the amber banner above. Announce that reason
            instead when it's set, so both surfaces agree. */}
          <p className="sr-only" role="status" aria-live="polite" data-testid="records-list-status">
            {filterErrorReason
              ? filterErrorMessage(t, filterErrorReason)
              : listStatus(t, {
                  count: records.items.length,
                  page: records.page,
                  pages: Math.max(1, Math.ceil(known / records.page_size)),
                  capped: records.total_capped,
                })}
          </p>

          <RecordPagination
            page={records.page}
            pageSize={records.page_size}
            total={known}
            capped={records.total_capped}
            itemCount={records.items.length}
            loading={loading}
            onGo={(next) => goTo({ page: next })}
            onPageSize={(size) => goTo({ page: 1, pageSize: size })}
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
