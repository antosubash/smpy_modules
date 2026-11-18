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
      texts: {
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
