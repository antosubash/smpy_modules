import { Head, Link, router, usePage } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type React from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { FilterBar, type FilterValue } from '../components/FilterBar';
import { RecordStatusBadge } from '../components/RecordStatusBadge';
import { deleteRecord } from '../utils/api';
import type { FilterOp, RecordPage, RecordRead, TypeRead } from '../utils/types';

type Props = { type: TypeRead; records: RecordPage };

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
 *  type's records, driven entirely by the URL (`?page=&filter=`) so it can
 *  be bookmarked or shared. Sorting is left to Phase 2's schema-driven list —
 *  nothing here reorders columns yet. */
function RecordList({ type, records }: Props) {
  const { t } = useT();
  const page = usePage<{ errors?: Record<string, string> }>();
  const search = new URL(page.url, window.location.origin).searchParams;
  const rawFilter = search.get('filter');
  const currentFilter = parseFilterParam(rawFilter);
  // Inertia's own `errors` bag — the Python view attaches `{filter:
  // "reindexing"}` when the applied filter's field is mid-reindex (design
  // doc §8.5) instead of failing the whole navigation. Real state, not a
  // toast: it stays on screen until the filter changes.
  const reindexing = page.props.errors?.filter === 'reindexing';

  const goTo = (next: { page?: number; filter?: string | null }) => {
    const params: Record<string, string> = {};
    const targetPage = next.page ?? records.page;
    if (targetPage > 1) params.page = String(targetPage);
    const targetFilter = next.filter === undefined ? rawFilter : next.filter;
    if (targetFilter) params.filter = targetFilter;
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

        {reindexing && (
          <div className="mb-4 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3 text-sm">
            {t('records.records.reindexing_notice', {
              defaultValue:
                'That field is being reindexed right now and cannot be filtered on yet. Try again shortly.',
            })}
          </div>
        )}

        {records.items.length === 0 ? (
          <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
            {t('records.records.empty', { defaultValue: 'No records yet' })}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>
                  {t('records.records.display_title', { defaultValue: 'Title' })}
                </TableHead>
                <TableHead>{t('records.records.status', { defaultValue: 'Status' })}</TableHead>
                <TableHead>
                  {t('records.records.updated_at', { defaultValue: 'Updated' })}
                </TableHead>
                <TableHead className="text-right">
                  {t('records.records.actions', { defaultValue: 'Actions' })}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.items.map((record) => (
                <TableRow key={record.uuid}>
                  <TableCell className="font-medium">
                    <Link
                      href={`/admin/records/${type.key}/${record.uuid}`}
                      className="hover:underline"
                    >
                      {record.display_title}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <RecordStatusBadge status={record.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {record.updated_at ?? record.created_at}
                  </TableCell>
                  <TableCell className="text-right">
                    <ConfirmDialog
                      trigger={
                        <Button type="button" variant="ghost" size="sm">
                          {t('records.records.delete', { defaultValue: 'Delete' })}
                        </Button>
                      }
                      title={t('records.records.delete', { defaultValue: 'Delete' })}
                      description={t('records.records.confirm_delete', {
                        defaultValue: 'Delete this record?',
                      })}
                      confirmLabel={t('records.records.delete', { defaultValue: 'Delete' })}
                      cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
                      pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
                      destructive
                      onConfirm={() => handleDelete(record)}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
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
