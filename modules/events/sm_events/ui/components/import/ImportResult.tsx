import { Button } from '@simple-module-py/ui/components/ui/button';
import type { Filter } from '../../hooks/useImport';
import type { ImportRow, ItemPage } from '../../utils/api-import';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';
import { ItemRows } from './ItemRows';

const OUTCOMES = ['created', 'updated', 'unchanged', 'skipped', 'failed'] as const;

/** What an import did: the counters, and the rows by outcome with their reasons in words. Each
 *  created or updated row opens its event in the editor. */
export function ImportResult({
  row,
  page,
  filter,
  setFilter,
  onDiscard,
}: {
  row: ImportRow;
  page: ItemPage | null;
  filter: Filter;
  setFilter: (next: Filter) => void;
  onDiscard: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.import.result;
  return (
    <section className="space-y-4" aria-label={t(copy.title)}>
      <h2 className="text-lg font-medium">{t(copy.title)}</h2>
      <p className="text-sm text-muted-foreground dark:text-zinc-400">
        <Name>{row.filename}</Name> · <Name>{row.calendar.name}</Name>
      </p>
      <fieldset className="flex flex-wrap gap-2" aria-label={t(keys.events.import.preview.filter)}>
        <Button
          type="button"
          size="sm"
          variant={filter.outcome === undefined ? 'default' : 'outline'}
          aria-pressed={filter.outcome === undefined}
          onClick={() => setFilter({})}
        >
          {t(keys.events.import.preview.all)} {row.total}
        </Button>
        {OUTCOMES.map((name) => (
          <Button
            key={name}
            type="button"
            size="sm"
            variant={filter.outcome === name ? 'default' : 'outline'}
            aria-pressed={filter.outcome === name}
            onClick={() => setFilter({ outcome: name })}
          >
            {t(copy[name], { count: row[name] })}
          </Button>
        ))}
      </fieldset>
      <ItemRows page={page} filter={filter} setFilter={setFilter} after />
      <Button type="button" variant="outline" onClick={onDiscard}>
        {t(keys.events.import.start_again)}
      </Button>
    </section>
  );
}
