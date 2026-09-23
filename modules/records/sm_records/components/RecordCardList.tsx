import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Fragment } from 'react';

import type { RecordSelection } from '../hooks/useRecordSelection';
import { type ListColumn, resolveListColumns } from '../utils/listing';
import { recordDisplayTitle } from '../utils/record-title';
import type { RecordRead, TypeRead } from '../utils/types';
import {
  ColumnValue,
  displayedColumns,
  envelopeLabel,
  RecordFlagBadges,
} from './RecordColumnCells';
import { RecordRowAction } from './RecordRowAction';
import { RecordSelectAllCell, RecordSelectCell } from './RecordSelectCell';
import { RecordLocaleBadge, RecordStatusBadge } from './RecordStatusBadge';

/** How many of the chosen columns a card lists under its title. A card is a
 *  phone's whole width; eight label/value lines per record turned a page of
 *  twenty-five into a scroll of two hundred lines. */
export const CARD_COLUMNS = 3;

/**
 * The record list below `md` (UX-R4, breakpoint raised from `sm` by U8): one
 *  card per record instead of a table
 * whose action column sat past the right edge of a 390px document, with no
 * scrollbar to say so on the screens that clipped it.
 *
 * Rendered *instead* of the `<Table>`, never beside it: `RecordTable` picks
 * one tree or the other from a media query, so a card carries its own test
 * id (`records-record-card`) and the table keeps the `records-record-row`
 * the suite counts rows by, with neither ever in the DOM twice.
 *
 * Sorting is not offered here: it belongs to the column headers this layout
 * has none of, and the URL still carries whatever the desktop screen set.
 *
 * U6: the table's header carries a "select all on this page" box
 * (`RecordSelectAllCell`) that this layout otherwise drops entirely — below
 * `md`, or at 200% zoom, ticking twenty-five rows one at a time was the only
 * way in. A small header above the cards mirrors it, rendered only when a
 * `selection` was actually given (the same gate every tick box here uses).
 *
 * Columns: Status and Language are badges beside the title when chosen (the
 * Invalid/stale markers always are); the first `CARD_COLUMNS` of the other
 * chosen columns, in the chosen order, are the card's label/value lines.
 */
export function RecordCardList({
  type,
  records,
  trashed = false,
  columns,
  selection,
  onDelete,
  onRestore,
  onPurge,
}: {
  type: TypeRead;
  records: RecordRead[];
  /** Same contract as `RecordTable`'s: absent means no tick boxes at all. */
  selection?: RecordSelection;
  trashed?: boolean;
  /** The columns this page displays (`RecordTable` passes them already
   *  resolved and position-trimmed). Absent means the type's default. */
  columns?: ListColumn[];
  onDelete: (record: RecordRead) => Promise<unknown>;
  onRestore: (record: RecordRead) => Promise<unknown>;
  onPurge: (record: RecordRead) => Promise<unknown>;
}) {
  const { t } = useT();
  const shown =
    columns ??
    displayedColumns(
      resolveListColumns({ type, showLocale: false, raw: null, saved: null }),
      records,
    );
  const showStatus = shown.some((column) => column.key === 'status');
  const showLocale = shown.some((column) => column.key === 'locale');
  const lines = shown
    .filter((column) => column.key !== 'status' && column.key !== 'locale')
    .slice(0, CARD_COLUMNS);
  return (
    <>
      {selection && (
        <div
          className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"
          data-testid="records-card-select-all"
        >
          <RecordSelectAllCell
            checked={selection.allSelected}
            indeterminate={selection.someSelected}
            onToggle={selection.toggleAll}
          />
          <span>
            {t('records.bulk.select_all_label', { defaultValue: 'Select all on this page' })}
          </span>
        </div>
      )}
      <ul className="space-y-3">
        {records.map((record) => {
          // U5: a record whose display field is empty otherwise leaves the
          // title link with no text and the row's own controls with no
          // accessible name — exactly the Invalid worklist's case.
          const title = recordDisplayTitle(record, type);
          return (
            <li
              key={record.uuid}
              data-testid="records-record-card"
              data-record-uuid={record.uuid}
              data-selected={selection?.isSelected(record.uuid) ? 'true' : undefined}
              className="rounded-lg border p-3"
            >
              <div className="flex items-start justify-between gap-2">
                {selection && (
                  <div className="pt-0.5">
                    <RecordSelectCell
                      checked={selection.isSelected(record.uuid)}
                      title={title}
                      onToggle={(extend) => selection.toggle(record.uuid, extend)}
                    />
                  </div>
                )}
                <div className="min-w-0">
                  <Link
                    href={`/admin/records/${type.key}/${record.uuid}`}
                    className="font-medium break-words hover:underline"
                  >
                    {title}
                  </Link>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {showStatus && <RecordStatusBadge status={record.status} />}
                    <RecordFlagBadges record={record} />
                    {showLocale && <RecordLocaleBadge locale={record.locale} />}
                  </div>
                </div>
                <div className="shrink-0">
                  <RecordRowAction
                    typeKey={type.key}
                    record={record}
                    title={title}
                    trashed={trashed}
                    onDelete={onDelete}
                    onRestore={onRestore}
                    onPurge={onPurge}
                  />
                </div>
              </div>
              <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-muted-foreground">
                {lines.map((column) => (
                  <Fragment key={column.key}>
                    <dt className="font-medium">
                      {column.kind === 'field' ? column.field.label : envelopeLabel(t, column.key)}
                    </dt>
                    <dd className="min-w-0 break-words" data-column={column.key}>
                      <ColumnValue column={column} record={record} />
                    </dd>
                  </Fragment>
                ))}
              </dl>
            </li>
          );
        })}
      </ul>
    </>
  );
}
