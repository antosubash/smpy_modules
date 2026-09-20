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
import { RecordDeleteDialog } from './RecordDeleteDialog';
import { RecordLocaleBadge, RecordStatusBadge, SchemaStaleBadge } from './RecordStatusBadge';
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
  trashed = false,
  showLocale = false,
  onSort,
  onDelete,
  onRestore,
}: {
  type: TypeRead;
  records: RecordRead[];
  sort: SortState;
  /** The list is showing the trash (`?trashed=true`): the row action is
   *  "Restore" rather than "Delete" — deleting an already-trashed row makes
   *  no sense, and restoring one that isn't does not either. */
  trashed?: boolean;
  /** The type is translatable and the module runs more than one content
   *  locale — an editor's question is "what exists", not "what exists in
   *  English" (design §4.4), hence a column rather than a filtered default. */
  showLocale?: boolean;
  onSort: (field: string) => void;
  onDelete: (record: RecordRead) => Promise<unknown>;
  onRestore: (record: RecordRead) => Promise<unknown>;
}) {
  const { t } = useT();
  const columns = listColumns(type);
  // A field named "Title" would otherwise share the display-title column's
  // accessible name (UX-12) — disambiguate only that collision.
  const titleLabel = t('records.records.display_title', { defaultValue: 'Title' });

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
          {showLocale && (
            <SortableHeader
              field="locale"
              label={t('records.records.locale', { defaultValue: 'Language' })}
              sort={sort}
              onSort={onSort}
            />
          )}
          {columns.map((field) => (
            <SortableHeader
              key={field.key}
              field={field.key}
              label={field.label}
              sort={sort}
              onSort={onSort}
              ariaLabel={field.label === titleLabel ? `${field.label} (${field.key})` : undefined}
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
          <TableRow
            key={record.uuid}
            data-testid="records-record-row"
            data-record-uuid={record.uuid}
          >
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
            {showLocale && (
              <TableCell>
                <RecordLocaleBadge locale={record.locale} />
              </TableCell>
            )}
            {columns.map((field) => (
              <TableCell key={field.key} className="text-muted-foreground">
                <RecordCell
                  field={field}
                  value={record.data[field.key]}
                  expanded={record.expanded?.[field.key] ?? undefined}
                />
              </TableCell>
            ))}
            <TableCell className="text-muted-foreground">{record.position}</TableCell>
            <TableCell className="text-muted-foreground">{record.published_at ?? '—'}</TableCell>
            <TableCell className="text-muted-foreground">
              {record.updated_at ?? record.created_at}
            </TableCell>
            <TableCell className="text-right">
              {trashed ? (
                <ConfirmDialog
                  trigger={
                    <Button type="button" variant="ghost" size="sm">
                      {t('records.editor.restore', { defaultValue: 'Restore' })}
                    </Button>
                  }
                  title={t('records.editor.restore', { defaultValue: 'Restore' })}
                  description={t('records.editor.confirm_restore', {
                    defaultValue: 'Restore this record?',
                  })}
                  confirmLabel={t('records.editor.restore', { defaultValue: 'Restore' })}
                  cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
                  pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
                  onConfirm={() => onRestore(record)}
                />
              ) : (
                <RecordDeleteDialog
                  typeKey={type.key}
                  uuid={record.uuid}
                  trigger={
                    <Button type="button" variant="ghost" size="sm">
                      {t('records.records.delete', { defaultValue: 'Delete' })}
                    </Button>
                  }
                  onConfirm={() => onDelete(record)}
                />
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
