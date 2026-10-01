import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useRef } from 'react';

import {
  type ListColumn,
  MAX_CHOSEN_COLUMNS,
  type ResolvedColumns,
  withColumn,
} from '../utils/listing';
import { ColumnOptionRow, columnControlId } from './ColumnOptionRow';
import { columnLabels } from './RecordColumnCells';

type Focus = { key: string; control: 'toggle' | 'up' | 'down' };

/**
 * The body of the record list's "Columns" menu: every column the type can
 * show, the shown ones first in their order (with move buttons), the rest
 * after in the type's own order. The field cap (`MAX_CHOSEN_COLUMNS`) counts
 * declared fields only; the record's own columns are toggles on top.
 *
 * Controlled: `resolved` is the list's current choice and every edit is
 * reported as the complete new key list — the caller owns where it is kept
 * (the link and this browser's saved default, see `useListColumns`).
 *
 * A move or a toggle re-renders the rows in a new order, and a moved row's
 * focused button can be detached on the way; focus is put back on the same
 * control of the same column afterwards — or on its other move button once
 * it reaches an end — so a keyboard user can press "down" repeatedly.
 */
export function ColumnChooserPanel({
  available,
  resolved,
  onChange,
  onReset,
}: {
  available: ListColumn[];
  resolved: ResolvedColumns;
  onChange: (keys: string[]) => void;
  onReset: () => void;
}) {
  const { t } = useT();
  const pendingFocus = useRef<Focus | null>(null);
  const heading = useRef<HTMLParagraphElement>(null);
  const chosenKeys = resolved.columns.map((column) => column.key);
  const order = chosenKeys.join(',');

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run exactly when the order changes
  useEffect(() => {
    const focus = pendingFocus.current;
    pendingFocus.current = null;
    if (!focus) return;
    const byId = (control: Focus['control']) =>
      document.getElementById(columnControlId(focus.key, control)) as HTMLButtonElement | null;
    const target = byId(focus.control);
    const other = focus.control === 'up' ? byId('down') : byId('up');
    (target && !target.disabled ? target : (other ?? target))?.focus();
  }, [order]);

  // The table's and the cards' own labels (`columnLabels`), so a declared
  // "Status" reads "Status (state)" in all three places.
  const labels = columnLabels(
    t,
    available,
    t('records.records.display_title', { defaultValue: 'Title' }),
  );
  const chosen = new Set(chosenKeys);
  const hidden = available.filter((column) => !chosen.has(column.key));
  const fieldCount = resolved.columns.filter((column) => column.kind === 'field').length;
  const atCap = fieldCount >= MAX_CHOSEN_COLUMNS;

  const toggle = (column: ListColumn) => {
    pendingFocus.current = { key: column.key, control: 'toggle' };
    onChange(
      chosen.has(column.key)
        ? chosenKeys.filter((key) => key !== column.key)
        : withColumn(resolved.columns, column),
    );
  };
  const move = (index: number, delta: -1 | 1) => {
    const next = [...chosenKeys];
    const [key] = next.splice(index, 1);
    next.splice(index + delta, 0, key);
    pendingFocus.current = { key, control: delta < 0 ? 'up' : 'down' };
    onChange(next);
  };

  return (
    <div className="grid gap-3 text-sm" data-testid="records-columns-panel">
      <div className="flex items-baseline justify-between gap-2">
        <p ref={heading} tabIndex={-1} className="font-medium outline-none">
          {t('records.columns.title', { defaultValue: 'Columns' })}
        </p>
        <p className="text-xs text-muted-foreground" data-testid="records-columns-count">
          {t('records.columns.count', {
            count: fieldCount,
            max: MAX_CHOSEN_COLUMNS,
            defaultValue: '{count} of {max} field column',
            defaultValue_other: '{count} of {max} field columns',
          })}
        </p>
      </div>

      <ul aria-label={t('records.columns.shown', { defaultValue: 'Shown' })}>
        {resolved.columns.map((column, index) => (
          <ColumnOptionRow
            key={column.key}
            column={column}
            label={labels.get(column.key) ?? column.key}
            chosen
            disabled={false}
            first={index === 0}
            last={index === resolved.columns.length - 1}
            onToggle={() => toggle(column)}
            onMove={(delta) => move(index, delta)}
          />
        ))}
      </ul>

      {hidden.length > 0 && (
        <div className="border-t pt-2">
          <p className="text-xs font-medium text-muted-foreground">
            {t('records.columns.hidden', { defaultValue: 'Hidden' })}
          </p>
          <ul aria-label={t('records.columns.hidden', { defaultValue: 'Hidden' })}>
            {hidden.map((column) => (
              <ColumnOptionRow
                key={column.key}
                column={column}
                label={labels.get(column.key) ?? column.key}
                chosen={false}
                disabled={atCap && column.kind === 'field'}
                first={false}
                last={false}
                onToggle={() => toggle(column)}
                onMove={() => {}}
              />
            ))}
          </ul>
        </div>
      )}

      {atCap && (
        <p className="text-xs text-muted-foreground" data-testid="records-columns-cap">
          {t('records.columns.cap_reached', {
            max: MAX_CHOSEN_COLUMNS,
            defaultValue: 'At most {max} field columns — hide one to show another.',
          })}
        </p>
      )}

      <div className="grid gap-1.5 border-t pt-2 text-xs text-muted-foreground">
        <p>
          {t('records.columns.help_link', {
            defaultValue:
              'Your choice is written into this page’s link (?columns=), so sharing the link shares these columns.',
          })}
        </p>
        <p>
          {t('records.columns.help_saved', {
            defaultValue:
              'This browser also remembers it as your default for this type. A link that names its own columns wins over that default.',
          })}
        </p>
        <p>
          {t('records.columns.help_export', {
            defaultValue: 'Export always contains every field, whatever is shown here.',
          })}
        </p>
      </div>

      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={resolved.source === 'default'}
        data-testid="records-columns-reset"
        onClick={() => {
          pendingFocus.current = null;
          // Reset disables itself (the list is now the default), and a
          // focused button that disables drops focus to <body>; the panel's
          // heading keeps it inside the popover (review 4, ux F10).
          heading.current?.focus();
          onReset();
        }}
      >
        {t('records.columns.reset', { defaultValue: 'Reset to default' })}
      </Button>
    </div>
  );
}
