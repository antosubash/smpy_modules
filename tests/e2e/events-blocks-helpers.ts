import { expect, type Page } from '@playwright/test';
import { addDays, wednesday } from './events-calendar-helpers';
import {
  type CreatedEvent,
  occurrencesOf,
  postCalendar,
  postEvent,
  publishEvent,
  setOverride,
} from './events-seed';
import { makePage, moduleCsrfHeader, uniqueSlug } from './helpers';

/** What events-blocks.spec.ts seeds (admin API only) and how it puts blocks on pagebuilder pages. */

const VIEW = '/admin/events/calendars';
export type Seeded = { id: string; revision: number; title: string };
export type BlocksSeed = {
  community: { id: string; slug: string; name: string };
  library: { id: string; slug: string; name: string };
  staff: { id: string; name: string };
  market: { id: string; slug: string; name: string };
  writing: Seeded & { deTitle: string };
  poetry: Seeded;
  call: Seeded;
  draft: Seeded;
  hidden: Seeded;
  stall: Seeded;
  /** Every event id the seed made: none may appear in anything public. */
  ids: string[];
  soon: string;
};

async function published(page: Page, seed: Parameters<typeof postEvent>[1]): Promise<Seeded> {
  const made: CreatedEvent = await postEvent(page, seed);
  return { id: made.id, title: seed.title, revision: await publishEvent(page, made) };
}

async function calendar(
  page: Page,
  name: string,
  visibility: 'public' | 'internal',
  zone?: string,
) {
  const made = await postCalendar(page, { name, visibility, ...(zone ? { zone } : {}) });
  const slug = (await (await page.request.get(`/api/events/calendars/${made.id}`)).json()).slug;
  return { id: made.id, slug: slug as string, name };
}

export async function seedBlocks(page: Page): Promise<BlocksSeed> {
  const community = await calendar(page, 'Community events', 'public');
  const library = await calendar(page, 'Library programme', 'public');
  const staff = await calendar(page, 'Staff only', 'internal');
  const market = await calendar(page, 'Seasonal market', 'public');
  const start = wednesday(1);
  const soon = addDays(new Date().toISOString().slice(0, 10), 2);

  const writing = await postEvent(page, {
    calendar: community.id,
    title: 'Writing circle',
    start: `${start}T10:00`,
    end: `${start}T11:30`,
    rrule: 'FREQ=WEEKLY;COUNT=5',
    venue: 'Seminar room',
    texts: { de: { title: 'Schreibkreis' } },
  });
  const originals = (
    await occurrencesOf(page, community.id, addDays(start, -1), addDays(start, 40))
  )
    .map((i) => i.original_start)
    .filter((o): o is string => !!o);
  let revision = await publishEvent(page, writing);
  revision = await setOverride(page, writing, revision, originals[1] ?? '', 'cancelled');
  const poetry = await published(page, {
    calendar: library.id,
    title: 'Poetry night',
    start: `${addDays(start, 1)}T19:00`,
    end: `${addDays(start, 1)}T21:00`,
    venue: 'Reading room',
  });
  const call = await published(page, {
    calendar: community.id,
    title: 'Transatlantic call',
    start: `${addDays(start, 2)}T14:00`,
    end: `${addDays(start, 2)}T15:00`,
    zone: 'America/New_York',
  });
  const draft = await postEvent(page, {
    calendar: community.id,
    title: 'Budget planning (draft)',
    start: `${addDays(start, 3)}T10:00`,
    end: `${addDays(start, 3)}T11:00`,
  });
  const hidden = await published(page, {
    calendar: staff.id,
    title: 'Staff retreat',
    start: `${addDays(start, 3)}T12:00`,
    end: `${addDays(start, 3)}T13:00`,
  });
  const stall = await published(page, {
    calendar: market.id,
    title: 'Winter market stall',
    start: `${soon}T09:00`,
    end: `${soon}T17:00`,
  });
  return {
    community,
    library,
    staff: { id: staff.id, name: staff.name },
    market,
    writing: { id: writing.id, revision, title: 'Writing circle', deTitle: 'Schreibkreis' },
    poetry,
    call,
    draft: { id: draft.id, revision: draft.revision, title: 'Budget planning (draft)' },
    hidden,
    stall,
    ids: [writing.id, poetry.id, call.id, draft.id, hidden.id, stall.id],
    soon,
  };
}

export const upcoming = (over: Record<string, unknown> = {}) => ({
  type: 'UpcomingEvents',
  props: {
    id: uniqueSlug('ue'),
    heading: 'Upcoming events',
    calendars: [],
    category: '',
    count: 8,
    layout: 'list',
    showImages: true,
    ...over,
  },
});
export const calendarBlock = (over: Record<string, unknown> = {}) => ({
  type: 'EventsCalendar',
  props: {
    id: uniqueSlug('ec'),
    calendars: [],
    defaultView: 'month',
    height: 'medium',
    ...over,
  },
});
const heading = (text: string) => ({
  type: 'Heading',
  props: { id: uniqueSlug('h'), text, level: 'h2' },
});
const text = (body: string) => ({ type: 'Text', props: { id: uniqueSlug('t'), text: body } });

/** A published pagebuilder page (and its German twin when asked): its slug. */
export async function blockPage(
  page: Page,
  blocks: unknown[],
  { german = false, title = 'What is on' } = {},
): Promise<{ slug: string; id: number }> {
  const slug = uniqueSlug('e2e-evblocks');
  const content = [
    heading(title),
    text('Join us for readings, workshops and the odd market. Everyone is welcome.'),
    ...blocks,
  ];
  const id = await makePage(page, { slug, publish: true, blocks: content });
  if (german) {
    const headers = await moduleCsrfHeader(page, '/pagebuilder/');
    const twin = await page.request.post(`/api/pagebuilder/pages/${id}/translations`, {
      headers,
      data: { locale: 'de', title: 'Was ist los' },
    });
    expect(twin.status(), await twin.text()).toBe(201);
    const published = await page.request.post(
      `/api/pagebuilder/pages/${((await twin.json()) as { id: number }).id}/publish`,
      { headers, data: {} },
    );
    expect(published.ok(), await published.text()).toBeTruthy();
  }
  return { slug, id };
}

export async function unpublishEvent(page: Page, event: Seeded): Promise<void> {
  const res = await page.request.post(`/api/events/events/${event.id}/unpublish`, {
    headers: await moduleCsrfHeader(page, VIEW),
    data: { expected_revision: event.revision },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
}

export async function setVisibility(page: Page, id: string, visibility: 'public' | 'internal') {
  const res = await page.request.put(`/api/events/calendars/${id}/visibility`, {
    headers: await moduleCsrfHeader(page, VIEW),
    data: { visibility },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
}
