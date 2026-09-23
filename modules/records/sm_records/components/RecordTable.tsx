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
import { type ResolvedColumns, resolveListColumns, type SortState } from '../utils/listing';
import { recordDisplayTitle } from '../utils/record-title';
import type { RecordRead, TypeRead } from '../utils/types';
import { RecordCardList } from './RecordCardList';
import { ColumnHeader, ColumnValue, displayedColumns, RecordFlagBadges } from './RecordColumnCells';
import { RecordRowAction } from './RecordRowAction';
import { RecordSelectAllCell, RecordSelectCell } from './RecordSelectCell';
import { SortableHeader } from './SortableHeader';

/** U6: the default columns are silent by design when a type has no indexed
 *  field — the table then shows only Title and Status, and nothing on the
 *  list screen said why until this. Only for the default view: a view that
 *  chose its own columns already knows what it asked for. Rendered under the table/cards either way,
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
 * The record list's table: the tick box, `display_title`, the chosen
 * `columns` in their chosen order (`resolveListColumns` — by default the
 * pre-chooser table: Status, the first four indexed fields, Position,
 * Published on, Updated) and Actions. Tick box, Title and Actions are fixed.
 * Split out of `RecordList` to keep that page under the 300-line cap.
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
  columns,
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
  /** The resolved column choice (`RecordList` owns the URL/saved state).
   *  Absent means the default columns for `type`/`showLocale`. */
  columns?: ResolvedColumns;
  onSort: (field: string) => void;
  onDelete: (record: RecordRead) => Promise<unknown>;
  onRestore: (record: RecordRead) => Promise<unknown>;
  onPurge: (record: RecordRead) => Promise<unknown>;
}) {
  const { t } = useT();
  const narrow = useIsNarrow();
  const resolved = columns ?? resolveListColumns({ type, showLocale, raw: null, saved: null });
  const shown = displayedColumns(resolved, records);
  const showStatus = shown.some((column) => column.key === 'status');
  const noIndexedNotice =
    resolved.source === 'default' && !shown.some((column) => column.kind === 'field');
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
          columns={shown}
          onDelete={onDelete}
          onRestore={onRestore}
          onPurge={onPurge}
        />
        {noIndexedNotice && <NoIndexedColumnsNotice typeKey={type.key} />}
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
            <SortableHeader field="display_title" label={titleLabel} sort={sort} onSort={onSort} />
            {shown.map((column) => (
              <ColumnHeader
                key={column.key}
                column={column}
                sort={sort}
                onSort={onSort}
                titleLabel={titleLabel}
              />
            ))}
            <TableHead className="text-right">
              {t('records.records.actions', { defaultValue: 'Actions' })}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {records.map((record) => {
            // U5: a record whose display field is empty otherwise leaves
            // the title link with no text and the row's own controls with
            // no accessible name — exactly the Invalid worklist's case.
            const title = recordDisplayTitle(record, type);
            return (
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
                      title={title}
                      onToggle={(extend) => selection.toggle(record.uuid, extend)}
                    />
                  </TableCell>
                )}
                <TableCell className="font-medium">
                  <Link
                    href={`/admin/records/${type.key}/${record.uuid}`}
                    className="hover:underline"
                  >
                    {title}
                  </Link>
                  {!showStatus && (record.invalid_since || record.schema_stale) && (
                    <span className="ml-2 inline-flex flex-wrap items-center gap-1.5 align-middle">
                      <RecordFlagBadges record={record} />
                    </span>
                  )}
                </TableCell>
                {shown.map((column) => (
                  <TableCell
                    key={column.key}
                    className={column.key === 'status' ? undefined : 'text-muted-foreground'}
                  >
                    <ColumnValue column={column} record={record} />
                  </TableCell>
                ))}
                <TableCell className="text-right">
                  <RecordRowAction
                    typeKey={type.key}
                    record={record}
                    title={title}
                    trashed={trashed}
                    onDelete={onDelete}
                    onRestore={onRestore}
                    onPurge={onPurge}
                  />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {noIndexedNotice && <NoIndexedColumnsNotice typeKey={type.key} />}
    </>
  );
}
