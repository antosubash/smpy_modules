/** "Calendar time / my time": which zone the grid is drawn in. Both buttons name their zone,
 *  so the choice is never a guess; when the two are the same zone it says so and stays. An
 *  all-day occurrence is dates and ignores the choice. */
import { Button } from '@simple-module-py/ui/components/ui/button';
import { keys, useT } from '../utils/i18n';
import type { TzMode } from './time/zones';

type Props = {
  mode: TzMode;
  /** The zone "calendar time" means right now (the one shown calendar's, else the tenant's). */
  calendarZone: string;
  /** The browser's zone. */
  myZone: string;
  /** Whether "calendar time" is offered; without it only the visitor's own zone is. */
  calendarTime?: boolean;
  onMode: (mode: TzMode) => void;
};

export function TimezoneToggle({ mode, calendarZone, myZone, calendarTime = true, onMode }: Props) {
  const { t } = useT();
  const copy = keys.events.calendar.tz;
  const option = (value: TzMode, label: string, zone: string) => (
    <Button
      type="button"
      size="sm"
      variant={mode === value ? 'default' : 'outline'}
      aria-pressed={mode === value}
      onClick={() => onMode(value)}
    >
      <span>{label}</span> <span className="text-xs opacity-80">{zone}</span>
    </Button>
  );
  return (
    <fieldset className="flex flex-wrap items-center gap-1" aria-label={t(copy.label)}>
      {calendarTime ? option('calendar', t(copy.calendar), calendarZone) : null}
      {option('mine', t(copy.mine), myZone)}
      {calendarTime && calendarZone === myZone ? (
        <span className="text-xs text-muted-foreground dark:text-zinc-400">{t(copy.same)}</span>
      ) : null}
    </fieldset>
  );
}
