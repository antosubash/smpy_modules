import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { useCallback, useSyncExternalStore } from 'react';

import { listColumns, type SortState } from '../utils/listing';
import type { RecordRead, TypeRead } from '../utils/types';
import { RecordCardList } from './RecordCardList';
import { RecordCell } from './RecordCell';
import { RecordRowAction } from './RecordRowAction';
import { RecordLocaleBadge, RecordStatusBadge, SchemaStaleBadge } from './RecordStatusBadge';
import { SortableHeader } from './SortableHeader';

/** Tailwind's `sm` breakpoint, as a query — the width at which the table
 *  stops fitting. Subscribed to rather than read once, so a rotation or a
 *  resized window swaps layouts without a reload. */
const NARROW = '(max-width: 639.98px)';

function matchesNarrow(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(NARROW).matches;
}

function useIsNarrow(): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    if (typeof window === 'undefined' || !window.matchMedia) return () => {};
    const query = window.matchMedia(NARROW);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  // The server snapshot is the table: nothing renders this on a server
  // today, and a wide layout is the safer thing to hydrate into.
  return useSyncExternalStore(subscribe, matchesNarrow, () => false);
}

/**
 * The record list's table: `display_title`, the type's first four indexed
 * fields as columns (design doc §7.2 — only an indexed field is worth a
 * column, since only an indexed field can be sorted or filtered on),
 * `position`/`published_at`/`updated_at` and actions. Split out of
 * `RecordList` to keep that page under the 300-line cap.
 *
 * Below `sm` the same records render as stacked cards instead (UX-R4): a
 * table of eight `whitespace-nowrap` columns cannot be reduced to the two or
 * three a phone holds, and what fell off the right edge of the document
 * there was the action column.
 *
 * One tree or the other, chosen by a media query rather than both rendered
 * with one hidden by a breakpoint class: a hidden copy is still in the DOM,
 * and a second row per record would double every `getByText(title)` in the
 * suite (and mount every row's delete dialog twice).
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
  const narrow = useIsNarrow();
  const columns = listColumns(type);
  // `position` is 0 on every record of every type that never set it, which
  // is most of them — a column of zeroes on a table that is already too wide
  // (UX-R25). Sorting by it stays reachable through the URL.
  const showPosition = records.some((record) => record.position !== 0);
  // A field named "Title" would otherwise share the display-title column's
  // accessible name (UX-12) — disambiguate only that collision.
  const titleLabel = t('records.records.display_title', { defaultValue: 'Title' });

  if (narrow) {
    return (
      <RecordCardList
        type={type}
        records={records}
        trashed={trashed}
        showLocale={showLocale}
        showPosition={showPosition}
        onDelete={onDelete}
        onRestore={onRestore}
      />
    );
  }

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
          {showPosition && (
            <SortableHeader
              field="position"
              label={t('records.records.position', { defaultValue: 'Position' })}
              sort={sort}
              onSort={onSort}
            />
          )}
          <SortableHeader
            field="published_at"
            label={t('records.records.published_at', { defaultValue: 'Published on' })}
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
            {showPosition && (
              <TableCell className="text-muted-foreground">{record.position}</TableCell>
            )}
            <TableCell className="text-muted-foreground">{record.published_at ?? '—'}</TableCell>
            <TableCell className="text-muted-foreground">
              {record.updated_at ?? record.created_at}
            </TableCell>
            <TableCell className="text-right">
              <RecordRowAction
                typeKey={type.key}
                record={record}
                trashed={trashed}
                onDelete={onDelete}
                onRestore={onRestore}
              />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
