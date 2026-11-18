/** The console calendar's state in the query string, so a view can be linked and survives a
 *  reload. Anything unknown or malformed is dropped on read (a hand-edited URL never breaks the
 *  page); "every calendar shown" is the default and is not written. */
import { isDate } from '../time/zones';
import { CALENDAR_VIEWS, type CalendarState, type CalendarView } from '../types';

export function readState(search: string): Partial<CalendarState> {
  const query = new URLSearchParams(search);
  const state: Partial<CalendarState> = {};
  const view = query.get('view');
  if (view && (CALENDAR_VIEWS as readonly string[]).includes(view))
    state.view = view as CalendarView;
  const date = query.get('date');
  if (date && isDate(date)) state.date = date;
  const zone = query.get('tz');
  if (zone === 'mine' || zone === 'calendar') state.tzMode = zone;
  const calendars = query.getAll('calendar');
  if (calendars.length) state.calendars = calendars;
  const categories = query.getAll('category');
  if (categories.length) state.categories = categories;
  const types = query.getAll('type');
  if (types.length) state.types = types;
  return state;
}

export function writeState(state: CalendarState, allCalendars: string[]): string {
  const query = new URLSearchParams();
  query.set('view', state.view);
  query.set('date', state.date);
  query.set('tz', state.tzMode);
  if (state.calendars.length && state.calendars.length < allCalendars.length) {
    for (const id of state.calendars) query.append('calendar', id);
  }
  for (const id of state.categories) query.append('category', id);
  for (const id of state.types) query.append('type', id);
  return `?${query}`;
}
