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
  canImport = false,
  onClear,
}: {
  typeKey: string;
  trashed: boolean;
  /** A `?filter=` is in force — including one the index layer refused, where
   *  the notice above says why and this box says what to do about it. */
  filtered: boolean;
  /** U10/U12: the index layer refused the filter (a reindex in progress, an
   *  unsupported operator, a bad value) — nothing was actually queried, so
   *  "No records match this filter" would assert something false about the
   *  data. `RecordList`'s own amber banner (`records-filter-error`) already
   *  says *why* in the server's own words; this box, once set, says only
   *  that nothing is shown *because* the filter was refused, rather than
   *  repeating that same sentence a second time immediately below it. */
  errorMessage?: string | null;
  /** U30: a brand-new type's empty box offered only "New record" — one row
   *  at a time — when Import (the toolbar button above) is how most people
   *  actually fill a new type. The control itself stays in the toolbar
   *  (its file input and dry-run state live in `RecordIoMenu`); this only
   *  makes it discoverable from the one screen an operator is looking at
   *  when they need it. Gated the same way the toolbar's own Import button
   *  is — `canEdit` — so a viewer is not pointed at a control they can't
   *  use. */
  canImport?: boolean;
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
            {errorMessage
              ? // U12: the reason itself is already on screen, in the amber
                // banner above — repeating it here read as the same sentence
                // twice, one above the other.
                t('records.records.empty_filter_refused', {
                  defaultValue: 'Nothing to show — the filter above could not be applied.',
                })
              : t('records.records.empty_filtered', {
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
          {canImport && (
            <p className="mt-2 text-sm" data-testid="records-empty-import-hint">
              {t('records.records.empty_import_hint', {
                defaultValue: 'Adding several at once? Use Import in the toolbar above.',
              })}
            </p>
          )}
        </>
      )}
    </div>
  );
}
