import { Head, Link, router, usePage } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type React from 'react';

import { FilterBar, type FilterValue } from '../components/FilterBar';
import { RecordTable } from '../components/RecordTable';
import { deleteRecord } from '../utils/api';
import { buildSortParam, filterErrorReasonKey, nextSort, parseSort } from '../utils/listing';
import type { FilterOp, RecordPage, RecordRead, TypeRead } from '../utils/types';

type Props = { type: TypeRead; records: RecordPage };

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
function RecordList({ type, records }: Props) {
  const { t } = useT();
  const page = usePage<{ errors?: Record<string, string> }>();
  const search = new URL(page.url, window.location.origin).searchParams;
  const rawFilter = search.get('filter');
  const rawSort = search.get('sort');
  const currentFilter = parseFilterParam(rawFilter);
  const currentSort = parseSort(search.toString());
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

  const goTo = (next: { page?: number; filter?: string | null; sort?: string | null }) => {
    const params: Record<string, string> = {};
    const targetPage = next.page ?? records.page;
    if (targetPage > 1) params.page = String(targetPage);
    const targetFilter = next.filter === undefined ? rawFilter : next.filter;
    if (targetFilter) params.filter = targetFilter;
    const targetSort = next.sort === undefined ? rawSort : next.sort;
    if (targetSort) params.sort = targetSort;
    router.get(`/admin/records/${type.key}`, params, {
      only: ['records', 'errors'],
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

  const handleDelete = async (record: RecordRead) => {
    await deleteRecord(type.key, record.uuid);
    router.reload({ only: ['records'] });
  };

  const hasPrev = records.page > 1;
  const hasNext = records.page * records.page_size < records.total;
  const rangeStart = records.total === 0 ? 0 : (records.page - 1) * records.page_size + 1;
  const rangeEnd = Math.min(records.page * records.page_size, records.total);

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
            <Button asChild>
              <Link href={`/admin/records/${type.key}/new`}>
                {t('records.records.new', { defaultValue: 'New record' })}
              </Link>
            </Button>
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
          />
        </div>

        {filterErrorReason && (
          <div className="mb-4 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm">
            {filterErrorMessage(t, filterErrorReason)}
          </div>
        )}

        {records.items.length === 0 ? (
          <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
            {t('records.records.empty', { defaultValue: 'No records yet' })}
          </div>
        ) : (
          <RecordTable
            type={type}
            records={records.items}
            sort={currentSort}
            onSort={handleSort}
            onDelete={handleDelete}
          />
        )}

        {records.total > records.page_size && (
          <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
            <span>
              {t('records.records.page_info', {
                start: rangeStart,
                end: rangeEnd,
                total: records.total,
                defaultValue: 'Showing {{start}}–{{end}} of {{total}}',
              })}
            </span>
            <div className="space-x-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!hasPrev}
                onClick={() => goTo({ page: records.page - 1 })}
              >
                {t('records.records.previous', { defaultValue: 'Previous' })}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!hasNext}
                onClick={() => goTo({ page: records.page + 1 })}
              >
                {t('records.records.next', { defaultValue: 'Next' })}
              </Button>
            </div>
          </div>
        )}
      </PageShell>
    </>
  );
}

RecordList.layout = (page: React.ReactNode) => <AdminLayout>{page}</AdminLayout>;
export default RecordList;
