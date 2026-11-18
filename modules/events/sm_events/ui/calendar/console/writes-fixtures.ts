import type { EventDetail, Occurrence } from '../../utils/types-events';
import type { OccurrenceChange } from '../types';

export const VIENNA = 'Europe/Vienna';

export const event = (extra: Partial<EventDetail> = {}): EventDetail =>
  ({
    id: 'e1',
    revision: 7,
    all_day: false,
    timezone: VIENNA,
    starts_at: '2026-03-23T09:00:00Z',
    ends_at: '2026-03-23T10:00:00Z',
    start_local: '2026-03-23T10:00',
    end_local: '2026-03-23T11:00',
    rrule: null,
    cancelled: false,
    overrides: [],
    ...extra,
  }) as EventDetail;

export const occurrence = (extra: Partial<Occurrence> = {}): Occurrence => ({
  source: 'events',
  key: 'e1:0',
  calendar_id: 'c1',
  start: '2026-03-23T09:00:00Z',
  end: '2026-03-23T10:00:00Z',
  all_day: false,
  timezone: VIENNA,
  start_date: null,
  end_date: null,
  title: 'Planning',
  lang: 'en',
  color: '#2563eb',
  url: null,
  status: 'confirmed',
  type: 'event',
  editable: true,
  event_id: 'e1',
  original_start: null,
  event_status: 'draft',
  ...extra,
});

/** A weekly Monday 10:00 Vienna series starting 2026-03-02, one hour long. */
export const series = (extra: Partial<EventDetail> = {}) =>
  event({
    rrule: 'FREQ=WEEKLY;BYDAY=MO',
    starts_at: '2026-03-02T09:00:00Z',
    ends_at: '2026-03-02T10:00:00Z',
    start_local: '2026-03-02T10:00',
    end_local: '2026-03-02T11:00',
    ...extra,
  });
export const instance = (extra: Partial<Occurrence> = {}) =>
  occurrence({ original_start: '2026-03-23T09:00:00Z', ...extra });

export const change = (
  o: Occurrence,
  kind: OccurrenceChange['kind'],
  start: string,
  end: string,
  allDay = false,
): OccurrenceChange => ({ occurrence: o, kind, start, end, allDay });

export const allDayOccurrence = (extra: Partial<Occurrence> = {}) =>
  occurrence({
    all_day: true,
    start: '2026-07-31T22:00:00Z',
    end: '2026-08-03T22:00:00Z',
    start_date: '2026-08-01',
    end_date: '2026-08-04',
    ...extra,
  });
export const allDayEvent = (extra: Partial<EventDetail> = {}) =>
  event({
    all_day: true,
    starts_at: '2026-07-31T22:00:00Z',
    ends_at: '2026-08-03T22:00:00Z',
    start_local: '2026-08-01',
    end_local: '2026-08-03',
    ...extra,
  });
