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
import { useIsNarrow } from '../hooks/useIsNarrow';
import type { RecordSelection } from '../hooks/useRecordSelection';
import { listColumns, type SortState } from '../utils/listing';
import type { RecordRead, TypeRead } from '../utils/types';
import { EMPTY_CELL, formatDateTime } from '../utils/values';
import { RecordCardList } from './RecordCardList';
import { RecordCell } from './RecordCell';
import { RecordRowAction } from './RecordRowAction';
import { RecordSelectAllCell, RecordSelectCell } from './RecordSelectCell';
import {
  InvalidBadge,
  RecordLocaleBadge,
  RecordStatusBadge,
  SchemaStaleBadge,
} from './RecordStatusBadge';
import { SortableHeader } from './SortableHeader';

/** U6: `listColumns` is silent by design when a type has no indexed field —
 *  the table then shows only Title and Status, and nothing on the list
 *  screen said why until this. Rendered under the table/cards either way,
 *  linking straight to the field editor rather than making the operator
 *  find their own way to "Indexed". */
function NoIndexedColumnsNotice({ typeKey }: { typeKey: string }) {
  const { t } = useT();
  return (
    <p className="mt-2 text-sm text-muted-foreground" data-testid="records-no-indexed-columns">
      {t('records.records.no_indexed_columns', {
        defaultValue: 'No fields are indexed, so only the title and status are shown.',
      })}{' '}
      <Link href={`/admin/records/types/${typeKey}`} className="underline">
        {t('records.records.no_indexed_columns_link', {
          defaultValue: 'Tick "Indexed" on a field to add a column.',
        })}
      </Link>
    </p>
  );
}

/**
 * The record list's table: `display_title`, the type's first four indexed
 * fields as columns (design doc §7.2 — only an indexed field is worth a
 * column, since only an indexed field can be sorted or filtered on),
 * `position`/`published_at`/`updated_at` and actions. Split out of
 * `RecordList` to keep that page under the 300-line cap.
 *
 * Below `md` the same records render as stacked cards instead (UX-R4; the
 * breakpoint was `sm` until U8): a table of eight `whitespace-nowrap`
 * columns cannot be reduced to the two or three a narrow viewport holds, and
 * between 640px and ~1000px it used to neither reduce nor reflow — it just
 * silently dropped Total, the dates and the Actions column off the right
 * edge with no scrollbar, shadow or fade to say more was there.
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
  selection,
  onSort,
  onDelete,
  onRestore,
  onPurge,
}: {
  type: TypeRead;
  records: RecordRead[];
  sort: SortState;
  /** Absent for a caller with no bulk actions to offer (a viewer, who cannot
   *  act on a selection anyway): the column is then not rendered at all,
   *  rather than rendered and inert. */
  selection?: RecordSelection;
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
  onPurge: (record: RecordRead) => Promise<unknown>;
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
      <>
        <RecordCardList
          type={type}
          records={records}
          selection={selection}
          trashed={trashed}
          showLocale={showLocale}
          showPosition={showPosition}
          onDelete={onDelete}
          onRestore={onRestore}
          onPurge={onPurge}
        />
        {columns.length === 0 && <NoIndexedColumnsNotice typeKey={type.key} />}
      </>
    );
  }

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            {selection && (
              <TableHead className="w-10">
                <RecordSelectAllCell
                  checked={selection.allSelected}
                  indeterminate={selection.someSelected}
                  onToggle={selection.toggleAll}
                />
              </TableHead>
            )}
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
              data-selected={selection?.isSelected(record.uuid) ? 'true' : undefined}
            >
              {selection && (
                <TableCell>
                  <RecordSelectCell
                    checked={selection.isSelected(record.uuid)}
                    title={record.display_title}
                    onToggle={(extend) => selection.toggle(record.uuid, extend)}
                  />
                </TableCell>
              )}
              <TableCell className="font-medium">
                <Link
                  href={`/admin/records/${type.key}/${record.uuid}`}
                  className="hover:underline"
                >
                  {record.display_title}
                </Link>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-1.5">
                  <RecordStatusBadge status={record.status} />
                  {record.invalid_since && <InvalidBadge since={record.invalid_since} />}
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
              <TableCell className="text-muted-foreground">
                {record.published_at ? formatDateTime(record.published_at) : EMPTY_CELL}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {formatDateTime(record.updated_at ?? record.created_at)}
              </TableCell>
              <TableCell className="text-right">
                <RecordRowAction
                  typeKey={type.key}
                  record={record}
                  trashed={trashed}
                  onDelete={onDelete}
                  onRestore={onRestore}
                  onPurge={onPurge}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {columns.length === 0 && <NoIndexedColumnsNotice typeKey={type.key} />}
    </>
  );
}
