import { useT } from '@simple-module-py/i18n';
import { TableHead } from '@simple-module-py/ui/components/ui/table';

import { disambiguateLabels } from '../utils/filters';
import type { EnvelopeColumnKey, ListColumn, ResolvedColumns, SortState } from '../utils/listing';
import type { RecordRead } from '../utils/types';
import { EMPTY_CELL, formatDateTime } from '../utils/values';
import { RecordCell } from './RecordCell';
import {
  InvalidBadge,
  RecordLocaleBadge,
  RecordStatusBadge,
  SchemaStaleBadge,
} from './RecordStatusBadge';
import { SortableHeader } from './SortableHeader';

// See `utils/list-errors.ts` for why `t` is typed this loosely.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

/** The header text of one of the record's own columns. One literal `t()`
 *  per key, so the untranslated-string check can read every one. */
export function envelopeLabel(t: Translate, key: EnvelopeColumnKey): string {
  switch (key) {
    case 'status':
      return t('records.records.status', { defaultValue: 'Status' });
    case 'locale':
      return t('records.records.locale', { defaultValue: 'Language' });
    case 'position':
      return t('records.records.position', { defaultValue: 'Position' });
    case 'published_at':
      return t('records.records.published_at', { defaultValue: 'Published on' });
    default:
      return t('records.records.updated_at', { defaultValue: 'Updated' });
  }
}

/**
 * Every column's header (and card) label, keyed by column key — the same
 * strings the Columns panel and the filter bar show. A declared field
 * labelled like one of the record's own columns ("Status", "Updated",
 * "Position", "Language") used to be a second, identical header beside it,
 * and "Status: Draft-ish" next to the status badge on a card (review 4, ux
 * F3). `disambiguateLabels` appends the key to every label that occurs more
 * than once among `columns` — pass every column the type *can* show, as the
 * panel does, so a header reads the same whether or not its twin is shown.
 * A field labelled like the Title column gets its key too (UX-12).
 */
export function columnLabels(
  t: Translate,
  columns: readonly ListColumn[],
  titleLabel: string,
): Map<string, string> {
  const labels = new Map(
    disambiguateLabels(
      columns.map((column) => ({
        key: column.key,
        label: column.kind === 'field' ? column.field.label : envelopeLabel(t, column.key),
      })),
    ).map((entry) => [entry.key, entry.label]),
  );
  for (const column of columns) {
    if (column.kind === 'field' && column.field.label === titleLabel) {
      labels.set(column.key, `${column.field.label} (${column.key})`);
    }
  }
  return labels;
}

/**
 * The columns a page of records actually renders, in order. `position` is 0
 * on every record of most types, so the *default* view still hides it while
 * every row on the page is 0 (UX-R25) — a column of zeroes on a table that
 * is already too wide. A view that chose Position shows it regardless.
 */
export function displayedColumns(resolved: ResolvedColumns, records: RecordRead[]): ListColumn[] {
  if (resolved.source !== 'default' || records.some((record) => record.position !== 0)) {
    return resolved.columns;
  }
  return resolved.columns.filter((column) => column.key !== 'position');
}

/** The Invalid / schema-stale markers. They ride in the Status cell, and
 *  move beside the title when a view hides Status, so a chooser can never
 *  hide that a record needs attention. */
export function RecordFlagBadges({ record }: { record: RecordRead }) {
  return (
    <>
      {record.invalid_since && <InvalidBadge since={record.invalid_since} />}
      {record.schema_stale && <SchemaStaleBadge />}
    </>
  );
}

/**
 * One column header. The record's own columns and indexed fields sort; a
 * non-indexed field cannot (the server sorts through the index only), so
 * its header is plain text with a muted "not sortable" beside it (the full
 * reason in a tooltip) rather than a button that would answer with a
 * `not_indexed` error.
 */
export function ColumnHeader({
  column,
  label,
  sort,
  onSort,
}: {
  column: ListColumn;
  /** From `columnLabels`: unambiguous among the type's columns. */
  label: string;
  sort: SortState;
  onSort: (field: string) => void;
}) {
  const { t } = useT();
  if (column.kind === 'envelope') {
    return <SortableHeader field={column.key} label={label} sort={sort} onSort={onSort} />;
  }
  const { field } = column;
  if (!field.indexed) {
    return (
      <TableHead data-testid="records-column-unsortable" data-column={field.key}>
        <span
          className="font-medium"
          title={t('records.columns.not_sortable', {
            defaultValue: "Not indexed, so this column can't be sorted or filtered.",
          })}
        >
          {label}
        </span>{' '}
        {/* Said on the page, not only in the hover title, which keyboard and
            screen-reader users never get (review 4, ux F14). */}
        <span
          className="text-xs font-normal text-muted-foreground"
          data-testid="records-column-note"
        >
          {t('records.columns.not_sortable_short', { defaultValue: 'not sortable' })}
        </span>
      </TableHead>
    );
  }
  return <SortableHeader field={field.key} label={label} sort={sort} onSort={onSort} />;
}

/** One column's value for one record — shared by the table and the cards. */
export function ColumnValue({ column, record }: { column: ListColumn; record: RecordRead }) {
  if (column.kind === 'field') {
    return (
      <RecordCell
        field={column.field}
        value={record.data[column.key]}
        expanded={record.expanded?.[column.key] ?? undefined}
      />
    );
  }
  switch (column.key) {
    case 'status':
      return (
        <div className="flex flex-wrap items-center gap-1.5">
          <RecordStatusBadge status={record.status} />
          <RecordFlagBadges record={record} />
        </div>
      );
    case 'locale':
      return <RecordLocaleBadge locale={record.locale} />;
    case 'position':
      return <>{record.position}</>;
    case 'published_at':
      return <>{record.published_at ? formatDateTime(record.published_at) : EMPTY_CELL}</>;
    default:
      return <>{formatDateTime(record.updated_at ?? record.created_at)}</>;
  }
}
