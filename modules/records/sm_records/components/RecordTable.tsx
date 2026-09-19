import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';

import { listColumns, type SortState } from '../utils/listing';
import type { RecordRead, TypeRead } from '../utils/types';
import { ConfirmDialog } from './ConfirmDialog';
import { RecordCell } from './RecordCell';
import { RecordStatusBadge, SchemaStaleBadge } from './RecordStatusBadge';
import { SortableHeader } from './SortableHeader';

/**
 * The record list's table: `display_title`, the type's first four indexed
 * fields as columns (design doc §7.2 — only an indexed field is worth a
 * column, since only an indexed field can be sorted or filtered on),
 * `position`/`published_at`/`updated_at` and actions. Split out of
 * `RecordList` to keep that page under the 300-line cap.
 */
export function RecordTable({
  type,
  records,
  sort,
  onSort,
  onDelete,
}: {
  type: TypeRead;
  records: RecordRead[];
  sort: SortState;
  onSort: (field: string) => void;
  onDelete: (record: RecordRead) => Promise<unknown>;
}) {
  const { t } = useT();
  const columns = listColumns(type);

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <SortableHeader
            field="display_title"
            label={t('records.records.display_title', { defaultValue: 'Title' })}
            sort={sort}
            onSort={onSort}
          />
          <SortableHeader
            field="status"
            label={t('records.records.status', { defaultValue: 'Status' })}
            sort={sort}
            onSort={onSort}
          />
          {columns.map((field) => (
            <SortableHeader
              key={field.key}
              field={field.key}
              label={field.label}
              sort={sort}
              onSort={onSort}
            />
          ))}
          <SortableHeader
            field="position"
            label={t('records.records.position', { defaultValue: 'Position' })}
            sort={sort}
            onSort={onSort}
          />
          <SortableHeader
            field="published_at"
            label={t('records.records.published_at', { defaultValue: 'Published' })}
            sort={sort}
            onSort={onSort}
          />
          <SortableHeader
            field="updated_at"
            label={t('records.records.updated_at', { defaultValue: 'Updated' })}
            sort={sort}
            onSort={onSort}
          />
          <TableHead className="text-right">
            {t('records.records.actions', { defaultValue: 'Actions' })}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {records.map((record) => (
          <TableRow key={record.uuid}>
            <TableCell className="font-medium">
              <Link href={`/admin/records/${type.key}/${record.uuid}`} className="hover:underline">
                {record.display_title}
              </Link>
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap items-center gap-1.5">
                <RecordStatusBadge status={record.status} />
                {record.schema_stale && <SchemaStaleBadge />}
              </div>
            </TableCell>
            {columns.map((field) => (
              <TableCell key={field.key} className="text-muted-foreground">
                <RecordCell field={field} value={record.data[field.key]} />
              </TableCell>
            ))}
            <TableCell className="text-muted-foreground">{record.position}</TableCell>
            <TableCell className="text-muted-foreground">{record.published_at ?? '—'}</TableCell>
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
                onConfirm={() => onDelete(record)}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
