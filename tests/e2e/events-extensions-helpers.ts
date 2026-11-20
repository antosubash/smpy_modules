import { expect, type Page } from '@playwright/test';

import { seedCalendar, seedEvent, wednesday } from './events-calendar-helpers';
import { publishEvent } from './events-seed';
import { moduleCsrfHeader } from './helpers';
import { apiCreateRecord, apiCreateType, uniqueTypeKey } from './records-helpers';

export const LABEL = 'Records with a date';

export type Seeded = {
  calendar: { id: string; name: string };
  key: string;
  day: string;
  uuid: string;
};

/** An internal calendar, a "Project deadlines" type (title, indexed `due` date) and one
 *  published deadline three weeks out, plus a plain event the same day. */
export async function seed(page: Page, label: string): Promise<Seeded> {
  const key = uniqueTypeKey('deadlines');
  await apiCreateType(page, {
    key,
    label: 'Project deadlines',
    label_plural: 'Project deadlines',
    display_field: 'title',
    fields: [
      { key: 'title', type: 'text', label: 'Title', indexed: false },
      { key: 'due', type: 'date', label: 'Due', indexed: true },
    ],
  });
  const day = wednesday(3);
  const record = await apiCreateRecord(page, key, {
    status: 'published',
    data: { title: 'Grant report due', due: day },
  });
  const calendar = await seedCalendar(page, { label, plain: true });
  const event = await seedEvent(page, {
    calendar: calendar.id,
    title: 'Kick-off meeting',
    start: `${day}T10:00`,
    end: `${day}T11:00`,
  });
  await publishEvent(page, event); // a viewer sees published events only
  return { calendar, key, day, uuid: record.uuid };
}

export async function enable(page: Page, s: Seeded, mapping: Record<string, unknown> = {}) {
  const headers = await moduleCsrfHeader(page, '/admin/events/calendars');
  const current = await (await page.request.get(`/api/events/calendars/${s.calendar.id}`)).json();
  const put = await page.request.put(`/api/events/calendars/${s.calendar.id}/sources`, {
    headers,
    data: {
      expected: current.sources_version,
      sources: [
        {
          id: 'records:dates',
          settings: { mappings: [{ type_key: s.key, field: 'due', ...mapping }] },
        },
      ],
    },
  });
  expect(put.status(), await put.text()).toBe(200);
}
