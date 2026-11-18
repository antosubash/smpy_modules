import { expect, type Page } from '@playwright/test';
import { addDays, seedCalendar, wednesday } from './events-calendar-helpers';
import {
  type CreatedEvent,
  occurrencesOf,
  postEvent,
  publishEvent,
  renameCalendarSlug,
  renameEventSlug,
  setOverride,
  slugOf,
} from './events-seed';
import { uniqueSlug } from './helpers';

/** What events-public.spec.ts seeds (through the admin API) and the guard every public page runs under. */

export const XSS_TITLE = '<img src=x onerror=alert(1)>';

/** A page error, a console error or a Content Security Policy message fails the test. */
export function guardPublic(page: Page, problems: string[]) {
  page.on('pageerror', (error) => problems.push(`pageerror: ${error}`));
  page.on('console', (message) => {
    const text = message.text();
    // A 404 *document* is a test subject (the module 404 page) and the browser logs it as a
    // console error; a failed script, style or fetch is reported by the response check below.
    if (text.startsWith('Failed to load resource')) return;
    if (message.type() === 'error' || text.includes('Content Security Policy')) {
      problems.push(`console ${message.type()}: ${text}`);
    }
  });
  page.on('response', (response) => {
    if (response.status() >= 400 && response.request().resourceType() !== 'document') {
      problems.push(`${response.status()} ${response.url()}`);
    }
  });
  page.on('dialog', (dialog) => {
    problems.push(`dialog: ${dialog.message()}`);
    void dialog.dismiss();
  });
}

export type PublicSeed = {
  pub: { id: string; slug: string; name: string };
  internal: { id: string; name: string; slug: string };
  start: string; // the series' first Wednesday
  weekly: { title: string; slug: string; dates: string[] };
  conference: { title: string; slug: string; deSlug: string; deTitle: string };
  talks: string[];
  xss: { slug: string };
  draft: { title: string; slug: string };
  hidden: { title: string; slug: string };
  renamed: { oldSlug: string; newSlug: string; title: string };
  oldCalendarSlug: string;
  newCalendarSlug: string;
};

async function publishedEvent(page: Page, seed: Parameters<typeof postEvent>[1]) {
  const event = await postEvent(page, seed);
  const revision = await publishEvent(page, event);
  return { ...event, revision } as CreatedEvent;
}

export async function seedPublic(page: Page): Promise<PublicSeed> {
  const tag = uniqueSlug('p');
  const pub = await seedCalendar(page, { visibility: 'public', label: `Public ${tag}` });
  const internal = await seedCalendar(page, { visibility: 'internal', label: `Internal ${tag}` });
  const pubSlug = (await (await page.request.get(`/api/events/calendars/${pub.id}`)).json()).slug;
  const start = wednesday(2);

  const weeklyTitle = `Weekly ${tag}`;
  const weekly = await publishedEvent(page, {
    calendar: pub.id,
    title: weeklyTitle,
    start: `${start}T10:00`,
    end: `${start}T11:00`,
    rrule: 'FREQ=WEEKLY;COUNT=6',
    venue: 'Seminar room',
    description: '<p>Every week, <strong>bring a pen</strong>.</p>',
  });
  const dates = [0, 1, 2, 3, 4, 5].map((n) => addDays(start, 7 * n));
  const items = await occurrencesOf(page, pub.id, addDays(start, -1), addDays(start, 50));
  const originals = items.map((i) => i.original_start).filter((o): o is string => !!o);
  expect(originals.length).toBe(6);
  let revision = weekly.revision;
  revision = await setOverride(page, weekly, revision, originals[1] ?? '', 'moved', {
    start: `${dates[1]}T11:00`,
    end: `${dates[1]}T12:00`,
  });
  revision = await setOverride(page, weekly, revision, originals[2] ?? '', 'cancelled');
  await setOverride(page, weekly, revision, originals[3] ?? '', 'skipped');

  const conferenceTitle = `Conference ${tag}`;
  const deTitle = `Konferenz ${tag}`;
  const conference = await publishedEvent(page, {
    calendar: pub.id,
    title: conferenceTitle,
    start: `${addDays(start, 2)}T09:00`,
    end: `${addDays(start, 2)}T17:00`,
    venue: 'Main hall',
    description: '<p>Two days of talks.</p>',
    texts: { de: { title: deTitle } },
  });
  const talks: string[] = [];
  for (const n of [1, 2]) {
    const title = `Talk ${n} ${tag}`;
    await publishedEvent(page, {
      calendar: pub.id,
      title,
      start: `${addDays(start, 2)}T1${n}:00`,
      end: `${addDays(start, 2)}T1${n}:45`,
      parent: conference.id,
    });
    talks.push(title);
  }

  const xssTitle = `${XSS_TITLE} ${tag}`;
  const xss = await publishedEvent(page, {
    calendar: pub.id,
    title: xssTitle,
    start: `${addDays(start, 3)}T18:00`,
    end: `${addDays(start, 3)}T19:00`,
  });

  const draftTitle = `Secret draft ${tag}`;
  const draft = await postEvent(page, {
    calendar: pub.id,
    title: draftTitle,
    start: `${addDays(start, 4)}T10:00`,
    end: `${addDays(start, 4)}T11:00`,
  });
  const hiddenTitle = `Internal only ${tag}`;
  const hidden = await publishedEvent(page, {
    calendar: internal.id,
    title: hiddenTitle,
    start: `${addDays(start, 4)}T12:00`,
    end: `${addDays(start, 4)}T13:00`,
  });

  const movedTitle = `Renamed ${tag}`;
  const renamed = await publishedEvent(page, {
    calendar: pub.id,
    title: movedTitle,
    start: `${addDays(start, 5)}T10:00`,
    end: `${addDays(start, 5)}T11:00`,
  });
  const oldSlug = await slugOf(page, renamed.id);
  const newSlug = `${oldSlug}-new`;
  await renameEventSlug(page, renamed.id, renamed.revision, movedTitle, newSlug);
  const newCalendarSlug = `${pubSlug}-new`;
  await renameCalendarSlug(page, pub.id, newCalendarSlug);

  return {
    pub: { ...pub, slug: newCalendarSlug },
    internal: {
      ...internal,
      slug: (await (await page.request.get(`/api/events/calendars/${internal.id}`)).json()).slug,
    },
    start,
    weekly: { title: weeklyTitle, slug: await slugOf(page, weekly.id), dates },
    conference: {
      title: conferenceTitle,
      slug: await slugOf(page, conference.id),
      deSlug: await slugOf(page, conference.id, 'de'),
      deTitle,
    },
    talks,
    xss: { slug: await slugOf(page, xss.id) },
    draft: { title: draftTitle, slug: await slugOf(page, draft.id) },
    hidden: { title: hiddenTitle, slug: await slugOf(page, hidden.id) },
    renamed: { oldSlug, newSlug, title: movedTitle },
    oldCalendarSlug: pubSlug,
    newCalendarSlug,
  };
}
