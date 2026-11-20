import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import type { Outcome } from '../../hooks/useEventActions';
import { formatInstant, formatWall, utcOffsetAt } from '../../utils/datetime';
import { keys, useT } from '../../utils/i18n';
import type { Override, OverrideInput, PreviewOccurrence } from '../../utils/types-events';
import { OverrideDialog } from './OverrideDialog';

type Props = {
  occurrences: PreviewOccurrence[];
  loading: boolean;
  error: string | null;
  overrides: Override[];
  allDay: boolean;
  timezone: string;
  /** Overrides apply to the saved series, so they need one without unsaved edits. */
  canOverride: boolean;
  saved: boolean;
  busy: boolean;
  onSet: (
    input: Omit<OverrideInput, 'expected_revision'>,
    onError?: (e: unknown) => void,
  ) => Promise<Outcome>;
  onClear: (id: number) => Promise<Outcome>;
};

const same = (a: string, b: string) => Date.parse(a) === Date.parse(b);

/** The next occurrences of the schedule in the form, in the event's local time,
 *  with skip, cancel and move for a saved series and Restore for a changed one. */
export function OccurrencesPreview(props: Props) {
  const { t, locale } = useT();
  const copy = keys.events.preview;
  const { occurrences, overrides, timezone, allDay } = props;
  const shown = new Set<number>();
  const rows = occurrences.map((occ) => {
    const found = overrides.find((o) => same(o.original_start, occ.start));
    if (found) shown.add(found.id);
    // A date-only (all-day) row has no clock time to qualify. Labels keep the plain `when`.
    const offset = allDay ? null : utcOffsetAt(occ.start, timezone);
    return { occ, found, when: formatWall(occ.start_local, locale), offset };
  });
  const others = overrides.filter((o) => !shown.has(o.id));
  const off = !props.canOverride || props.busy;
  const restore = (o: Override, when: string) => (
    <Button
      variant="outline"
      size="sm"
      disabled={off}
      aria-label={t(copy.restore_for, { when })}
      onClick={() => void props.onClear(o.id)}
    >
      {t(copy.restore)}
    </Button>
  );
  const described = (o: Override) =>
    o.kind === 'moved' && o.start_local
      ? t(copy.moved_to, { when: formatWall(o.start_local, locale) })
      : null;
  return (
    <section className="grid gap-2" aria-label={t(copy.title)}>
      <h3 className="text-sm font-medium">{t(copy.title)}</h3>
      {props.saved && !props.canOverride && (
        <p className="text-sm text-muted-foreground dark:text-zinc-400">{t(copy.save_first)}</p>
      )}
      {props.error && (
        <p role="alert" className="text-sm text-destructive dark:text-red-400">
          {props.error}
        </p>
      )}
      {props.loading && (
        <p role="status" className="text-sm">
          {t(keys.events.common.loading)}
        </p>
      )}
      {!props.loading && !props.error && rows.length === 0 && (
        <p className="text-sm text-muted-foreground dark:text-zinc-400">{t(copy.none)}</p>
      )}
      <ul className="grid gap-2">
        {rows.map(({ occ, found, when, offset }) => (
          <li key={occ.start} className="flex flex-wrap items-center gap-2 text-sm">
            <span className={found?.kind === 'skipped' ? 'line-through' : undefined}>{when}</span>
            {offset && <span className="text-muted-foreground dark:text-zinc-400">({offset})</span>}
            {found && <Badge variant="secondary">{t(copy[`kind_${found.kind}`])}</Badge>}
            {found && described(found) && <span>{described(found)}</span>}
            {props.saved && (
              <span className="ml-auto flex gap-1 whitespace-nowrap">
                {found ? (
                  restore(found, when)
                ) : (
                  <>
                    {(['skipped', 'cancelled'] as const).map((kind) => (
                      <Button
                        key={kind}
                        variant="outline"
                        size="sm"
                        disabled={off}
                        aria-label={t(kind === 'skipped' ? copy.skip_for : copy.cancel_for, {
                          when,
                        })}
                        onClick={() => void props.onSet({ original_start: occ.start, kind })}
                      >
                        {t(kind === 'skipped' ? copy.skip : copy.cancel)}
                      </Button>
                    ))}
                    <OverrideDialog
                      originalStart={occ.start}
                      label={when}
                      start={occ.start_local}
                      end={occ.end_local}
                      allDay={allDay}
                      timezone={timezone}
                      disabled={off}
                      onSet={props.onSet}
                    />
                  </>
                )}
              </span>
            )}
          </li>
        ))}
      </ul>
      {others.length > 0 && (
        <>
          <h3 className="mt-2 text-sm font-medium">{t(copy.others)}</h3>
          <ul className="grid gap-2">
            {others.map((o) => {
              const when = formatInstant(o.original_start, timezone, locale);
              return (
                <li key={o.id} className="flex flex-wrap items-center gap-2 text-sm">
                  <span>{when}</span>
                  <Badge variant="secondary">{t(copy[`kind_${o.kind}`])}</Badge>
                  {described(o) && <span>{described(o)}</span>}
                  <span className="ml-auto">{restore(o, when)}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
