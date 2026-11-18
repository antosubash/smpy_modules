import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useCallback, useMemo } from 'react';
import { ConsoleCalendar } from '../ui/calendar/console/ConsoleCalendar';
import { readState, writeState } from '../ui/calendar/console/urlState';
import type { CalendarInfo, CalendarState } from '../ui/calendar/types';
import { keys, useT } from '../ui/utils/i18n';
import type { Category } from '../ui/utils/types';

type Props = {
  calendars: CalendarInfo[];
  categories: Category[];
  default_timezone: string;
  content_locales: string[];
  editor_url: string;
};

/** The URL's state, minus anything naming a calendar the viewer does not have. */
function stateFromUrl(known: string[]): Partial<CalendarState> {
  const state = readState(window.location.search);
  const calendars = (state.calendars ?? []).filter((id) => known.includes(id));
  const { calendars: _unfiltered, ...rest } = state;
  return calendars.length ? { ...rest, calendars } : rest;
}

export default function CalendarPage({
  calendars,
  categories,
  default_timezone,
  content_locales,
}: Props) {
  const { t } = useT();
  const copy = keys.events.calendar;
  const ids = useMemo(() => calendars.map((c) => c.id), [calendars]);
  // Read once: the component owns its state from then on and reports every change.
  const initialState = useMemo(() => stateFromUrl(ids), [ids]);
  const mirror = useCallback(
    (state: CalendarState) => {
      const { pathname, hash } = window.location;
      window.history.replaceState(
        window.history.state,
        '',
        `${pathname}${writeState(state, ids)}${hash}`,
      );
    },
    [ids],
  );
  return (
    <>
      <Head title={t(copy.title)} />
      <PageShell title={t(copy.title)} description={t(copy.subtitle)}>
        <ConsoleCalendar
          calendars={calendars}
          categories={categories}
          defaultTimezone={default_timezone}
          contentLocales={content_locales}
          initialState={initialState}
          onStateChange={mirror}
        />
      </PageShell>
    </>
  );
}
CalendarPage.layout = [AuthenticatedLayout];
