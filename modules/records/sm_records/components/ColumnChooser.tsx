import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@simple-module-py/ui/components/ui/popover';
import { Columns3Icon } from 'lucide-react';

import { type ListColumn, MAX_CHOSEN_COLUMNS, type ResolvedColumns } from '../utils/listing';
import { ColumnChooserPanel } from './ColumnChooserPanel';

/** The record-list toolbar's "Columns" menu button. A popover rather than a
 *  dropdown menu: it holds tick boxes and buttons that stay open across
 *  several edits, which a menu (one item, then close) is not for. */
export function ColumnChooser({
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
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" data-testid="records-columns-button">
          <Columns3Icon className="size-4 opacity-60" aria-hidden="true" />
          {t('records.columns.button', { defaultValue: 'Columns' })}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="max-h-[70vh] w-80 max-w-[calc(100vw-2rem)] overflow-y-auto"
      >
        <ColumnChooserPanel
          available={available}
          resolved={resolved}
          onChange={onChange}
          onReset={onReset}
        />
      </PopoverContent>
    </Popover>
  );
}

/** What a `?columns=` link asked for that the list could not show: keys this
 *  type has no column for, and field columns past the cap. Informational —
 *  the rest of the link still applies. */
export function ColumnsNotice({ resolved }: { resolved: ResolvedColumns }) {
  const { t } = useT();
  if (resolved.unknown.length === 0 && resolved.truncated === 0) return null;
  return (
    <div
      className="mb-4 rounded-lg border p-3 text-sm text-muted-foreground"
      role="status"
      data-testid="records-columns-notice"
    >
      {resolved.unknown.length > 0 && (
        <p>
          {t('records.columns.unknown', {
            count: resolved.unknown.length,
            keys: resolved.unknown.join(', '),
            defaultValue: 'Ignored a column this type doesn’t have: {keys}.',
            defaultValue_other: 'Ignored {count} columns this type doesn’t have: {keys}.',
          })}
        </p>
      )}
      {resolved.truncated > 0 && (
        <p>
          {t('records.columns.truncated', {
            count: resolved.truncated,
            max: MAX_CHOSEN_COLUMNS,
            defaultValue: 'Only {max} field columns can be shown; {count} more was left out.',
            defaultValue_other:
              'Only {max} field columns can be shown; {count} more were left out.',
          })}
        </p>
      )}
    </div>
  );
}
