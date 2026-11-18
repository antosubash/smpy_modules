import { expect, type Page } from '@playwright/test';

import { moduleCsrfHeader } from './helpers';

/** The one place the events specs create calendars and events (through the API). Each spec
 *  still seeds its own data with unique names, so every file stands alone. */

const CSRF_VIEW = '/admin/events/calendars';
export const ZONE = 'Europe/Vienna';

export type CalendarSeed = {
  name: string;
  visibility?: 'private' | 'internal' | 'public';
  color?: string;
  zone?: string;
};
export type CreatedCalendar = { id: string; slug: string; name: string };

export async function postCalendar(page: Page, seed: CalendarSeed): Promise<CreatedCalendar> {
  const created = await page.request.post('/api/events/calendars', {
    headers: await moduleCsrfHeader(page, CSRF_VIEW),
    data: {
      name: seed.name,
      color: seed.color ?? '#2563eb',
      description: null,
      default_timezone: seed.zone ?? ZONE,
      visibility: seed.visibility ?? 'private',
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const body = (await created.json()) as { id: string; slug: string };
  return { id: body.id, slug: body.slug, name: seed.name };
}

export type EventSeed = {
  calendar: string;
  title: string;
  start: string; // YYYY-MM-DDTHH:MM, or YYYY-MM-DD when allDay
  end: string;
  allDay?: boolean;
  rrule?: string | null;
  zone?: string;
  venue?: string | null;
  description?: string;
  /** A sub-event of this event (same calendar, not recurring). */
  parent?: string;
  /** More languages: `{ de: { title: 'Konzert' } }`. */
  texts?: Record<string, { title: string; slug?: string }>;
};
export type CreatedEvent = { id: string; revision: number; calendar_id: string };

export async function postEvent(page: Page, seed: EventSeed): Promise<CreatedEvent> {
  const created = await page.request.post('/api/events/events', {
    headers: await moduleCsrfHeader(page, CSRF_VIEW),
    data: {
      calendar_id: seed.calendar,
      times: {
        all_day: seed.allDay ?? false,
        timezone: seed.zone ?? ZONE,
        start: seed.start,
        end: seed.end,
      },
      rrule: seed.rrule ?? null,
      venue_name: seed.venue ?? null,
      parent_id: seed.parent ?? null,
      texts: {
        ...seed.texts,
        en: {
          title: seed.title,
          ...(seed.description === undefined ? {} : { description: seed.description }),
        },
      },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  return (await created.json()) as CreatedEvent;
}

/** Draft -> in review -> published, as the admin (who holds events.publish). */
export async function publishEvent(page: Page, event: CreatedEvent): Promise<number> {
  const headers = await moduleCsrfHeader(page, CSRF_VIEW);
  const submit = await page.request.post(`/api/events/events/${event.id}/submit`, {
    headers,
    data: { expected_revision: event.revision },
  });
  expect(submit.status(), await submit.text()).toBe(200);
  const { revision } = (await submit.json()) as { revision: number };
  const approve = await page.request.post(`/api/events/events/${event.id}/approve`, {
    headers,
    data: { expected_revision: revision },
  });
  expect(approve.status(), await approve.text()).toBe(200);
  return ((await approve.json()) as { revision: number }).revision;
}

export type ApiOccurrence = { original_start: string | null; start: string };

/** The occurrences of a calendar in a window: the exact `original_start` instants an override names. */
export async function occurrencesOf(
  page: Page,
  calendar: string,
  from: string,
  to: string,
): Promise<ApiOccurrence[]> {
  const url = `/api/events/occurrences?calendar=${calendar}&start=${from}T00:00:00Z&end=${to}T00:00:00Z`;
  const res = await page.request.get(url);
  expect(res.status(), await res.text()).toBe(200);
  return ((await res.json()) as { items: ApiOccurrence[] }).items;
}

/** Skip, cancel or move one occurrence of a published series. Returns the new revision. */
export async function setOverride(
  page: Page,
  event: { id: string },
  revision: number,
  original: string,
  kind: 'skipped' | 'cancelled' | 'moved',
  times?: { start: string; end: string },
): Promise<number> {
  const res = await page.request.post(`/api/events/events/${event.id}/overrides`, {
    headers: await moduleCsrfHeader(page, CSRF_VIEW),
    data: { expected_revision: revision, original_start: original, kind, ...times },
  });
  expect(res.status(), await res.text()).toBe(200);
  return ((await res.json()) as { event_revision: number }).event_revision;
}

/** The event's slug in a language, as the server derived or stored it. */
export async function slugOf(page: Page, id: string, locale = 'en'): Promise<string> {
  const res = await page.request.get(`/api/events/events/${id}`);
  const body = (await res.json()) as { texts: Record<string, { slug: string }> };
  return body.texts[locale]?.slug ?? '';
}

/** Rename a slug through the API (what records the redirect). Returns the new revision. */
export async function renameEventSlug(
  page: Page,
  id: string,
  revision: number,
  title: string,
  slug: string,
): Promise<number> {
  const res = await page.request.patch(`/api/events/events/${id}`, {
    headers: await moduleCsrfHeader(page, CSRF_VIEW),
    data: { expected_revision: revision, texts: { en: { title, slug } } },
  });
  expect(res.status(), await res.text()).toBe(200);
  return ((await res.json()) as { revision: number }).revision;
}

export async function renameCalendarSlug(page: Page, id: string, slug: string): Promise<void> {
  const res = await page.request.patch(`/api/events/calendars/${id}`, {
    headers: await moduleCsrfHeader(page, CSRF_VIEW),
    data: { slug },
  });
  expect(res.status(), await res.text()).toBe(200);
}
