// @vitest-environment happy-dom

import { updateI18n } from '@simple-module-py/i18n';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import { indexProps, item } from './public-support';
import { flush, stubFetch } from './support';
import { act, click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));
const { default: PublicIndex } = await import('../../pages/PublicIndex');

beforeEach(() => {
  fakeGrid.reset();
  history.replaceState(null, '', '/events/');
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
  updateI18n({ locale: 'en', messages: {} });
});

it('renders month groups with localized month names', async () => {
  const view = await mount(
    <PublicIndex
      {...indexProps({ locale: 'de', groups: [{ month: '2026-07', items: [item()] }] })}
    />,
  );
  expect(view.find('h2')?.textContent).toBe('Juli 2026');
  expect(view.find('li a')?.textContent).toBe('Concert');
  expect(view.find('li a')?.getAttribute('href')).toBe('/events/concert');
});

it('marks a fallback item with its own language', async () => {
  const view = await mount(
    <PublicIndex
      {...indexProps({
        locale: 'de',
        groups: [
          {
            month: '2026-07',
            items: [
              item({ lang: 'en', title: 'Conference' }),
              item({ key: 'x', lang: 'de', title: 'Konzert' }),
            ],
          },
        ],
      })}
    />,
  );
  const links = view.all('li a');
  expect(links[0]?.getAttribute('lang')).toBe('en');
  expect(links[0]?.getAttribute('hreflang')).toBe('en');
  expect(links[1]?.hasAttribute('lang')).toBe(false);
});

it('shows cancelled and rescheduled markers', async () => {
  const view = await mount(
    <PublicIndex
      {...indexProps({
        groups: [
          {
            month: '2026-07',
            items: [
              item({ status: 'cancelled' }),
              item({ key: 'b', rescheduled: true, title: 'Moved' }),
            ],
          },
        ],
      })}
    />,
  );
  expect(view.host.textContent).toContain('Cancelled');
  expect(view.host.textContent).toContain('Rescheduled');
});

it('names the timezone only when it differs from the calendar', async () => {
  const view = await mount(
    <PublicIndex
      {...indexProps({
        groups: [
          {
            month: '2026-07',
            items: [item({ show_timezone: true, timezone: 'America/New_York' })],
          },
        ],
      })}
    />,
  );
  expect(view.find('time')?.textContent).toContain('(America/New_York)');
  expect(view.find('time')?.textContent).toContain('10:00');
});

it('paging links keep the category', async () => {
  const view = await mount(
    <PublicIndex {...indexProps({ page: 2, page_count: 3, category: 'talks' })} />,
  );
  const prev = view.find('a[rel=prev]');
  const next = view.find('a[rel=next]');
  expect(prev?.getAttribute('href')).toBe('/events/?category=talks');
  expect(next?.getAttribute('href')).toBe('/events/?category=talks&page=3');
  expect(view.host.textContent).toContain('Page 2 of 3');
});

it('has no pager for one page', async () => {
  const view = await mount(<PublicIndex {...indexProps()} />);
  expect(view.find('a[rel=next]')).toBeNull();
});

it('category filter links carry ?category=', async () => {
  const view = await mount(<PublicIndex {...indexProps({ category: 'talks' })} />);
  const links = view.all('nav a');
  const talks = links.find((a) => a.textContent === 'Talks');
  expect(talks?.getAttribute('href')).toBe('/events/?category=talks');
  expect(talks?.getAttribute('aria-current')).toBe('true');
  expect(links.find((a) => a.textContent === 'All categories')?.getAttribute('href')).toBe(
    '/events/',
  );
});

it('the calendar tab mounts the grid read-only', async () => {
  stubFetch({ 'GET /events/api/occurrences': { items: [], truncated: false } });
  await mount(<PublicIndex {...indexProps({ view: 'calendar' })} />);
  await flush();
  expect(fakeGrid.last).not.toBeNull();
  expect(fakeGrid.last?.editing).toBeUndefined();
});

it('the grid fetcher calls the public API', async () => {
  const calls = stubFetch({ 'GET /events/api/occurrences': { items: [], truncated: false } });
  await mount(<PublicIndex {...indexProps({ view: 'calendar', locale: 'de' })} />);
  await flush();
  await act(async () =>
    fakeGrid.emitRange(
      { start: '2026-06-28T00:00:00Z', end: '2026-08-02T00:00:00Z' } as never,
      'Juli 2026',
    ),
  );
  await flush();
  const call = calls.find((c) => c.url.startsWith('/events/api/occurrences'));
  expect(call).toBeDefined();
  const url = new URL(call?.url ?? '', 'http://x');
  expect(url.searchParams.get('locale')).toBeTruthy();
  expect(url.searchParams.has('start') && url.searchParams.has('end')).toBe(true);
  expect(calls.every((c) => c.method === 'GET')).toBe(true);
});

it('a grid change is written to the address', async () => {
  stubFetch({ 'GET /events/api/occurrences': { items: [], truncated: false } });
  await mount(<PublicIndex {...indexProps({ view: 'calendar' })} />);
  await flush();
  await act(async () =>
    fakeGrid.emitRange(
      { start: '2026-06-28T00:00:00Z', end: '2026-08-02T00:00:00Z' } as never,
      'Juli',
      'month',
      '2026-07-15',
    ),
  );
  await flush();
  const query = new URLSearchParams(window.location.search);
  expect(query.get('view')).toBe('calendar');
  expect(query.get('date')).toBe('2026-07-15');
});

it('the subscribe box shows https and webcal links', async () => {
  const view = await mount(<PublicIndex {...indexProps()} />);
  await flush();
  const input = view.find<HTMLInputElement>('input[readonly]');
  expect(input?.value).toBe(`${window.location.origin}/events/calendar.ics`);
  const webcal = view.all('a').find((a) => a.getAttribute('href')?.startsWith('webcal:'));
  expect(webcal?.getAttribute('href')).toBe(
    `${window.location.origin.replace(/^https?:/, 'webcal:')}/events/calendar.ics`,
  );
  const writeText = vi.fn(async () => undefined);
  vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
  await click(view.button('Copy link'));
  expect(writeText).toHaveBeenCalledWith(input?.value);
  expect(view.host.textContent).toContain('Link copied');
});

it('renders no admin link', async () => {
  const view = await mount(<PublicIndex {...indexProps({ view: 'list' })} />);
  expect(view.host.innerHTML).not.toContain('/admin/');
});

it('a calendar page names its calendar and feed', async () => {
  const calendar = indexProps().calendars[0];
  const view = await mount(
    <PublicIndex
      {...indexProps({ calendar: calendar ?? null, title: 'Team', feed_url: '/events/c/team.ics' })}
    />,
  );
  expect(view.find('h1')?.textContent).toBe('Team');
  expect(view.find<HTMLInputElement>('input[readonly]')?.value).toContain('/events/c/team.ics');
});

it('says so when nothing is coming up', async () => {
  const view = await mount(<PublicIndex {...indexProps({ groups: [] })} />);
  expect(view.host.textContent).toContain('No upcoming events.');
});

it('sets the document language', async () => {
  await mount(<PublicIndex {...indexProps({ locale: 'de' })} />);
  expect(document.documentElement.lang).toBe('de');
});
