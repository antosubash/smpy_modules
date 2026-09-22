import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

/**
 * The record list with nothing in it — which is three different situations,
 * and used to be two sentences (UX-R1).
 *
 * A filter that matches nothing rendered the same "No records yet" a
 * genuinely empty type gets: the message asserted something false about the
 * data, and the whole point of keeping the filter in the URL is that someone
 * arrives here from a shared link with no idea a filter is in force. So the
 * filtered state says so and offers the same "Clear" the bar above carries,
 * and the genuinely-empty state finally offers the "New record" call to
 * action it never had.
 */
export function RecordListEmpty({
  typeKey,
  trashed,
  filtered,
  errorMessage,
  onClear,
}: {
  typeKey: string;
  trashed: boolean;
  /** A `?filter=` is in force — including one the index layer refused, where
   *  the notice above says why and this box says what to do about it. */
  filtered: boolean;
  /** U10: the index layer refused the filter (a reindex in progress, an
   *  unsupported operator, a bad value) — nothing was actually queried, so
   *  "No records match this filter" would assert something false about the
   *  data. When this is set it *replaces* that line rather than sitting
   *  beside it, so the box never makes two contradictory claims at once. */
  errorMessage?: string | null;
  onClear: () => void;
}) {
  const { t } = useT();
  return (
    <div
      className="rounded-lg border border-dashed p-8 text-center text-muted-foreground"
      data-testid="records-empty-state"
    >
      {trashed ? (
        <p>{t('records.trash.empty', { defaultValue: 'No trashed records' })}</p>
      ) : filtered ? (
        <>
          <p data-testid={errorMessage ? 'records-empty-filter-error' : 'records-empty-filtered'}>
            {errorMessage ??
              t('records.records.empty_filtered', {
                defaultValue: 'No records match this filter.',
              })}
          </p>
          <Button type="button" variant="outline" size="sm" className="mt-4" onClick={onClear}>
            {t('records.records.filter_clear', { defaultValue: 'Clear' })}
          </Button>
        </>
      ) : (
        <>
          <p>{t('records.records.empty', { defaultValue: 'No records yet' })}</p>
          <Button asChild size="sm" className="mt-4">
            <Link href={`/admin/records/${typeKey}/new`}>
              {t('records.records.new', { defaultValue: 'New record' })}
            </Link>
          </Button>
        </>
      )}
    </div>
  );
}
