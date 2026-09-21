import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Fragment } from 'react';

import { listColumns } from '../utils/listing';
import type { RecordRead, TypeRead } from '../utils/types';
import { RecordCell } from './RecordCell';
import { RecordRowAction } from './RecordRowAction';
import { RecordLocaleBadge, RecordStatusBadge, SchemaStaleBadge } from './RecordStatusBadge';

/**
 * The record list below `sm` (UX-R4): one card per record instead of a table
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
 */
export function RecordCardList({
  type,
  records,
  trashed = false,
  showLocale = false,
  showPosition = false,
  onDelete,
  onRestore,
}: {
  type: TypeRead;
  records: RecordRead[];
  trashed?: boolean;
  showLocale?: boolean;
  /** Some row on this page has a non-zero `position` (UX-R25) — otherwise
   *  the meta line spends a row on a zero every record shares. */
  showPosition?: boolean;
  onDelete: (record: RecordRead) => Promise<unknown>;
  onRestore: (record: RecordRead) => Promise<unknown>;
}) {
  const { t } = useT();
  const columns = listColumns(type);
  return (
    <ul className="space-y-3">
      {records.map((record) => (
        <li
          key={record.uuid}
          data-testid="records-record-card"
          data-record-uuid={record.uuid}
          className="rounded-lg border p-3"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <Link
                href={`/admin/records/${type.key}/${record.uuid}`}
                className="font-medium break-words hover:underline"
              >
                {record.display_title}
              </Link>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                <RecordStatusBadge status={record.status} />
                {record.schema_stale && <SchemaStaleBadge />}
                {showLocale && <RecordLocaleBadge locale={record.locale} />}
              </div>
            </div>
            <div className="shrink-0">
              <RecordRowAction
                typeKey={type.key}
                record={record}
                trashed={trashed}
                onDelete={onDelete}
                onRestore={onRestore}
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
                <dd>{record.published_at}</dd>
              </>
            )}
            <dt className="font-medium">
              {t('records.records.updated_at', { defaultValue: 'Updated' })}
            </dt>
            <dd>{record.updated_at ?? record.created_at}</dd>
          </dl>
        </li>
      ))}
    </ul>
  );
}
