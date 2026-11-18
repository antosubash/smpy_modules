import { Button } from '@simple-module-py/ui/components/ui/button';
import type { Filter } from '../../hooks/useImport';
import { droppedText, type ImportRow, type ItemPage } from '../../utils/api-import';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';
import { ItemRows } from './ItemRows';

/** What will happen, per item, before anything is written: counts as filters, the rows, what the
 *  file held that is not imported, and the two ways to go on. */
export function PreviewTable({
  row,
  page,
  filter,
  setFilter,
  canPublish,
  busy,
  onApply,
  onDiscard,
}: {
  row: ImportRow;
  page: ItemPage | null;
  filter: Filter;
  setFilter: (next: Filter) => void;
  canPublish: boolean;
  busy: boolean;
  onApply: (publish: boolean) => void;
  onDiscard: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.import;
  const dropped = Object.entries(row.dropped);
  const chips: [string | undefined, string, number][] = [
    [undefined, t(copy.preview.all), row.total],
    ['new', t(copy.preview.verdict.new), row.counts.new ?? 0],
    ['update', t(copy.preview.verdict.update), row.counts.update ?? 0],
    ['skip', t(copy.preview.verdict.skip), row.counts.skip ?? 0],
  ];
  return (
    <section className="space-y-4" aria-label={t(copy.preview.title)}>
      <h2 className="text-lg font-medium">{t(copy.preview.title)}</h2>
      <p className="text-sm text-muted-foreground">
        <Name>{row.filename}</Name> · <Name>{row.calendar.name}</Name>
      </p>
      <fieldset className="flex flex-wrap gap-2" aria-label={t(copy.preview.filter)}>
        {chips.map(([verdict, label, count]) => (
          <Button
            key={verdict ?? 'all'}
            type="button"
            size="sm"
            variant={filter.verdict === verdict ? 'default' : 'outline'}
            aria-pressed={filter.verdict === verdict}
            onClick={() => setFilter(verdict ? { verdict } : {})}
          >
            {label} {count}
          </Button>
        ))}
      </fieldset>
      <ItemRows page={page} filter={filter} setFilter={setFilter} after={false} />
      {dropped.length > 0 && (
        <p className="text-sm" data-testid="events-import-dropped">
          {t(copy.preview.dropped)}:{' '}
          {dropped.map(([name, n]) => `${droppedText(name)} ${n}`).join(', ')}
        </p>
      )}
      <p className="text-sm text-muted-foreground">{t(copy.locked_hint)}</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" disabled={busy || row.total === 0} onClick={() => onApply(false)}>
          {t(copy.apply_drafts)}
        </Button>
        {canPublish && (
          <Button
            type="button"
            variant="outline"
            disabled={busy || row.total === 0}
            onClick={() => onApply(true)}
          >
            {t(copy.apply_publish)}
          </Button>
        )}
        <Button type="button" variant="ghost" onClick={onDiscard}>
          {t(copy.start_again)}
        </Button>
      </div>
    </section>
  );
}
