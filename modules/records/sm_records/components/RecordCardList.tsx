import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Fragment } from 'react';

import type { RecordSelection } from '../hooks/useRecordSelection';
import { listColumns } from '../utils/listing';
import { recordDisplayTitle } from '../utils/record-title';
import type { RecordRead, TypeRead } from '../utils/types';
import { formatDateTime } from '../utils/values';
import { RecordCell } from './RecordCell';
import { RecordRowAction } from './RecordRowAction';
import { RecordSelectAllCell, RecordSelectCell } from './RecordSelectCell';
import {
  InvalidBadge,
  RecordLocaleBadge,
  RecordStatusBadge,
  SchemaStaleBadge,
} from './RecordStatusBadge';

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
 */
export function RecordCardList({
  type,
  records,
  trashed = false,
  showLocale = false,
  showPosition = false,
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
  showLocale?: boolean;
  /** Some row on this page has a non-zero `position` (UX-R25) — otherwise
   *  the meta line spends a row on a zero every record shares. */
  showPosition?: boolean;
  onDelete: (record: RecordRead) => Promise<unknown>;
  onRestore: (record: RecordRead) => Promise<unknown>;
  onPurge: (record: RecordRead) => Promise<unknown>;
}) {
  const { t } = useT();
  const columns = listColumns(type);
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
                    <RecordStatusBadge status={record.status} />
                    {record.invalid_since && <InvalidBadge since={record.invalid_since} />}
                    {record.schema_stale && <SchemaStaleBadge />}
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
                {columns.map((field) => (
                  <Fragment key={field.key}>
                    <dt className="font-medium">{field.label}</dt>
                    <dd className="min-w-0 break-words">
                      <RecordCell
                        field={field}
                        value={record.data[field.key]}
                        expanded={record.expanded?.[field.key] ?? undefined}
                      />
                    </dd>
                  </Fragment>
                ))}
                {showPosition && (
                  <>
                    <dt className="font-medium">
                      {t('records.records.position', { defaultValue: 'Position' })}
                    </dt>
                    <dd>{record.position}</dd>
                  </>
                )}
                {record.published_at && (
                  <>
                    <dt className="font-medium">
                      {t('records.records.published_at', { defaultValue: 'Published on' })}
                    </dt>
                    <dd>{formatDateTime(record.published_at)}</dd>
                  </>
                )}
                <dt className="font-medium">
                  {t('records.records.updated_at', { defaultValue: 'Updated' })}
                </dt>
                <dd>{formatDateTime(record.updated_at ?? record.created_at)}</dd>
              </dl>
            </li>
          );
        })}
      </ul>
    </>
  );
}
