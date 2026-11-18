/** Today, previous, next, the title the grid reports and the view switcher. Every control
 *  has a name and is a plain button, so Tab and Enter operate it. */
import { Button } from '@simple-module-py/ui/components/ui/button';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ReactNode } from 'react';
import { keys, useT } from '../utils/i18n';
import { TimezoneToggle } from './TimezoneToggle';
import type { TzMode } from './time/zones';
import { CALENDAR_VIEWS, type CalendarView } from './types';

type Props = {
  title: string;
  view: CalendarView;
  onView: (view: CalendarView) => void;
  onToday: () => void;
  onPrev: () => void;
  onNext: () => void;
  tz: {
    mode: TzMode;
    calendarZone: string;
    myZone: string;
    calendarTime: boolean;
    onMode: (mode: TzMode) => void;
  };
  start?: ReactNode;
  end?: ReactNode;
};

export function Toolbar({ title, view, onView, onToday, onPrev, onNext, tz, start, end }: Props) {
  const { t } = useT();
  const copy = keys.events.calendar;
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-2"
      role="toolbar"
      aria-label={t(copy.toolbar.label)}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {start}
        <Button type="button" size="sm" variant="outline" onClick={onToday}>
          {t(copy.toolbar.today)}
        </Button>
        <Button
          type="button"
          size="icon"
          variant="outline"
          aria-label={t(copy.toolbar.previous)}
          onClick={onPrev}
        >
          <ChevronLeft aria-hidden="true" />
        </Button>
        <Button
          type="button"
          size="icon"
          variant="outline"
          aria-label={t(copy.toolbar.next)}
          onClick={onNext}
        >
          <ChevronRight aria-hidden="true" />
        </Button>
        <h2
          tabIndex={-1}
          className="min-w-0 text-lg font-semibold max-sm:order-first max-sm:basis-full"
          aria-live="polite"
          data-testid="calendar-title"
        >
          {title}
        </h2>
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {end}
        <TimezoneToggle {...tz} />
        <fieldset className="flex min-w-0 flex-wrap gap-1" aria-label={t(copy.toolbar.views)}>
          {CALENDAR_VIEWS.map((name) => (
            <Button
              key={name}
              type="button"
              size="sm"
              variant={view === name ? 'default' : 'outline'}
              aria-pressed={view === name}
              onClick={() => onView(name)}
            >
              {t(copy.views[name])}
            </Button>
          ))}
        </fieldset>
      </div>
    </div>
  );
}
