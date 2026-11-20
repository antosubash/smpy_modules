/** The saved event's seats per date and the warning for a capacity set below them. */

import type { useRegistrationCounts } from '../../hooks/useRegistrationCounts';
import { formatWall } from '../../utils/datetime';
import { keys, useT } from '../../utils/i18n';

type State = ReturnType<typeof useRegistrationCounts>['state'];

/** Lowering the capacity below seats already taken is allowed (nobody is removed); it says so, with
 *  the numbers, before the save. */
export function CapacityWarning({ capacity, state }: { capacity: number | null; state: State }) {
  const { t, locale } = useT();
  if (capacity === null || state.kind !== 'ready') return null;
  const worst = [...state.items].sort((a, b) => b.taken - a.taken)[0];
  if (!worst || worst.taken <= capacity) return null;
  return (
    <p
      role="status"
      className="rounded-md border border-amber-500 p-2 text-sm"
      data-testid="capacity-warning"
    >
      {t(keys.events.registration.capacity_warning, {
        taken: worst.taken,
        capacity,
        date: worst.start_local ? formatWall(worst.start_local, locale) : '',
      })}
    </p>
  );
}

export function Counts({ state, retry }: { state: State; retry: () => void }) {
  const { t, locale } = useT();
  const copy = keys.events.registration;
  if (state.kind === 'idle') return null;
  return (
    <div className="grid gap-2" data-testid="registration-counts">
      <h3 className="text-sm font-medium">{t(copy.counts_title)}</h3>
      {state.kind === 'loading' ? (
        <p role="status" className="text-sm text-muted-foreground">
          {t(copy.counts_loading)}
        </p>
      ) : state.kind === 'error' ? (
        <p role="alert" className="text-sm text-destructive">
          {t(copy.counts_error)}{' '}
          <button type="button" className="underline" onClick={retry}>
            {t(copy.counts_retry)}
          </button>
        </p>
      ) : state.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(copy.counts_empty)}</p>
      ) : (
        <table className="text-sm">
          <tbody>
            {state.items.map((row) => (
              <tr key={row.occurrence_key}>
                <th scope="row" className="pr-4 text-left font-normal">
                  {row.start_local ? formatWall(row.start_local, locale) : t(copy.counts_gone)}
                </th>
                <td>
                  {row.capacity === null
                    ? t(copy.counts_taken_open, { taken: row.taken })
                    : t(copy.counts_taken, { taken: row.taken, capacity: row.capacity })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
