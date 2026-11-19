// @vitest-environment happy-dom

import { updateI18n } from '@simple-module-py/i18n';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import { loadCatalogue } from '../utils/PageLocale';
import { item } from './public-support';
import { mount, ready } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: PublicEvent } = await import('../../pages/PublicEvent');

import type { PublicEventProps } from '../public/types';

function props(overrides: Partial<PublicEventProps> = {}): PublicEventProps {
  return {
    type: 'event',
    public_extra: {},
    locale: 'en',
    title: 'Concert',
    summary: 'An evening of music',
    description_tree: [{ t: 'p', c: ['Come along'] }],
    timezone: 'Europe/Vienna',
    all_day: false,
    when: {
      start: '2026-07-06T08:00:00Z',
      end: '2026-07-06T09:30:00Z',
      all_day: false,
      start_local: '2026-07-06T10:00',
      end_local: '2026-07-06T11:30',
      start_date: null,
      end_date: null,
      status: 'scheduled',
      previous_start_local: null,
      date_param: null,
    },
    series: null,
    cancelled: false,
    place: {
      mode: 'in_person',
      venue_name: 'Konzerthaus',
      address: 'Lothringerstr. 20',
      online_url: null,
      latitude: null,
      longitude: null,
    },
    organiser: null,
    image: null,
    category: null,
    calendar: { slug: 'team', name: 'Team', color: '#2563eb', url: '/events/c/team' },
    parent: null,
    sub_events: [],
    registration_url: 'https://register.example/x',
    registration: {
      mode: 'external',
      url: 'https://register.example/x',
      provider: null,
      target: null,
      occurrence_key: null,
      upcoming: [],
    },
    ics_url: '/events/concert.ics',
    canonical_url: 'https://x.example/events/concert',
    alternates: [],
    json_ld: null,
    index_in_search: true,
    ...overrides,
  };
}

const RealDateTimeFormat = Intl.DateTimeFormat;
let browserZone = 'Europe/Vienna';

/** A plain function, not an arrow: the code under test calls the mock with `new`. */
function formatterWithBrowserZone(...args: ConstructorParameters<typeof RealDateTimeFormat>) {
  const format = new RealDateTimeFormat(...args);
  if (args[1] === undefined) {
    return { resolvedOptions: () => ({ ...format.resolvedOptions(), timeZone: browserZone }) };
  }
  return format;
}

function viewerZone(zone: string) {
  browserZone = zone;
  vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(formatterWithBrowserZone as never);
}

beforeEach(() => {
  history.replaceState(null, '', '/events/concert');
});
// The German catalogue is a lazy chunk: have it in place so a test does not wait on the loader.
beforeAll(() => loadCatalogue('de'));

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '';
  updateI18n({ locale: 'en', messages: {} });
});

it('shows times in the event timezone', async () => {
  viewerZone('Europe/Vienna');
  const view = await mount(<PublicEvent {...props()} />);
  expect(view.find('time')?.textContent).toContain('10:00');
  expect(view.find('time')?.textContent).toContain('(Europe/Vienna)');
  expect(view.host.textContent).not.toContain('Your time');
});

it('shows a viewer-time hint when the browser zone differs', async () => {
  viewerZone('America/New_York');
  const view = await mount(<PublicEvent {...props()} />);
  expect(view.host.textContent).toMatch(/Your time: .*4:00/);
});

it('all-day shows dates only and no hint', async () => {
  viewerZone('America/New_York');
  const view = await mount(
    <PublicEvent
      {...props({
        all_day: true,
        when: {
          start: '2026-03-28T23:00:00Z',
          end: '2026-03-29T22:00:00Z',
          all_day: true,
          start_local: '2026-03-29',
          end_local: '2026-03-29',
          start_date: '2026-03-29',
          end_date: '2026-03-30',
          status: 'scheduled',
          previous_start_local: null,
          date_param: null,
        },
      })}
    />,
  );
  expect(view.find('time')?.textContent).not.toMatch(/\d:\d\d/);
  expect(view.host.textContent).not.toContain('Your time');
});

it('a series lists its next occurrences with date links', async () => {
  const view = await mount(
    <PublicEvent
      {...props({
        when: null,
        series: {
          rule: 'FREQ=WEEKLY;COUNT=8',
          start_local: '2026-03-16T10:00',
          next: [
            {
              date_param: '2026-04-06',
              url: '/events/concert?date=2026-04-06',
              start_local: '2026-04-06T10:00',
              end_local: '2026-04-06T11:00',
              status: 'cancelled',
            },
            {
              date_param: '2026-04-20',
              url: '/events/concert?date=2026-04-20',
              start_local: '2026-04-20T10:00',
              end_local: '2026-04-20T11:00',
              status: 'scheduled',
            },
          ],
        },
      })}
    />,
  );
  const links = view.all('ul a').map((a) => a.getAttribute('href'));
  expect(links).toEqual(['/events/concert?date=2026-04-06', '/events/concert?date=2026-04-20']);
  expect(view.host.textContent).toContain('(cancelled)');
  expect(view.host.textContent).toContain('Every week');
});

const NONE = {
  mode: 'none' as const,
  url: null,
  provider: null,
  target: null,
  occurrence_key: null,
  upcoming: [],
};

it('a cancelled event shows the banner and hides registration', async () => {
  const view = await mount(
    <PublicEvent {...props({ cancelled: true, registration_url: null, registration: NONE })} />,
  );
  expect(view.find('[role=status]')?.textContent).toBe('This event has been cancelled');
  expect(view.host.textContent).not.toContain('Register');
});

it('a cancelled date says so for that date', async () => {
  const base = props();
  const view = await mount(
    <PublicEvent
      {...props({
        cancelled: true, // what the server sends for a cancelled date as well
        when: base.when && { ...base.when, status: 'cancelled', date_param: '2026-07-06' },
        registration_url: null,
        registration: NONE,
      })}
    />,
  );
  expect(view.find('[role=status]')?.textContent).toBe('This date has been cancelled');
});

it('a rescheduled occurrence shows its previous time', async () => {
  const base = props();
  const view = await mount(
    <PublicEvent
      {...props({
        when: base.when && {
          ...base.when,
          status: 'rescheduled',
          previous_start_local: '2026-07-05T10:00',
        },
      })}
    />,
  );
  expect(view.host.textContent).toContain('Rescheduled from');
  expect(view.host.textContent).toContain('10:00');
});

it('shows the place by mode', async () => {
  const inPerson = await mount(<PublicEvent {...props()} />);
  expect(inPerson.host.textContent).toContain('Konzerthaus');
  expect(inPerson.host.textContent).not.toContain('Join online');
  await inPerson.unmount();
  const online = await mount(
    <PublicEvent
      {...props({
        place: {
          mode: 'online',
          venue_name: 'Hall',
          address: null,
          online_url: 'https://meet.example/x',
          latitude: null,
          longitude: null,
        },
      })}
    />,
  );
  expect(online.host.textContent).not.toContain('Hall');
  expect(online.find('a[href="https://meet.example/x"]')?.textContent).toBe('Join online');
  await online.unmount();
  const hybrid = await mount(
    <PublicEvent
      {...props({
        place: {
          mode: 'hybrid',
          venue_name: 'Hall',
          address: null,
          online_url: 'https://meet.example/x',
          latitude: 48.2,
          longitude: 16.4,
        },
      })}
    />,
  );
  expect(hybrid.host.textContent).toContain('Hall');
  expect(hybrid.find('a[href="https://meet.example/x"]')).not.toBeNull();
  expect(hybrid.find('a[href*="openstreetmap.org"]')).not.toBeNull();
});

it('lists sub-events and names the parent', async () => {
  const view = await mount(
    <PublicEvent
      {...props({
        sub_events: [item({ key: 't1', title: 'Opening talk', url: '/events/talk' })],
        parent: { title: 'Conference', url: '/events/conf' },
      })}
    />,
  );
  expect(view.find('a[href="/events/conf"]')?.textContent).toBe('Part of Conference');
  expect(view.find('a[href="/events/talk"]')?.textContent).toBe('Opening talk');
});

it('add to calendar links the .ics', async () => {
  const view = await mount(<PublicEvent {...props()} />);
  expect(view.find('a[href="/events/concert.ics"]')?.textContent).toBe('Add to calendar');
  expect(view.find('a[href="https://register.example/x"]')?.getAttribute('rel')).toContain(
    'nofollow',
  );
});

it('the language switch skips x-default', async () => {
  const view = await mount(
    <PublicEvent
      {...props({
        alternates: [
          { locale: 'en', url: 'https://x.example/events/concert' },
          { locale: 'de', url: 'https://x.example/de/events/konzert' },
          { locale: 'x-default', url: 'https://x.example/events/concert' },
        ],
      })}
    />,
  );
  const links = view.all('nav a');
  expect(links.map((a) => a.getAttribute('hreflang'))).toEqual(['en', 'de']);
  expect(links[0]?.getAttribute('aria-current')).toBe('true');
});

it('renders the description as elements, never HTML', async () => {
  const view = await mount(
    <PublicEvent
      {...props({ description_tree: [{ t: 'p', c: ['<img src=x onerror=alert(1)>'] }] })}
    />,
  );
  expect(view.host.querySelector('img')).toBeNull();
  expect(view.host.textContent).toContain('<img src=x onerror=alert(1)>');
});

it('sets the document language', async () => {
  const view = await mount(<PublicEvent {...props({ locale: 'de' })} />);
  await ready(view, 'h1');
  expect(document.documentElement.lang).toBe('de');
});
