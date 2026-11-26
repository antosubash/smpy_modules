// @vitest-environment happy-dom

import { updateI18n } from '@simple-module-py/i18n';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { item } from '../page-tests/public-support';
import { stubFetch } from '../page-tests/support';
import { mount, ready } from '../page-tests/test-dom';
import { loadCatalogue } from '../utils/PageLocale';

const page = { props: { locale: 'en' } };
vi.mock('@inertiajs/react', () => ({ usePage: () => page }));
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));
const { EventsCalendarRender } = await import('./EventsCalendarRender');
const { UpcomingEventsRender } = await import('./UpcomingEventsRender');

beforeAll(() => loadCatalogue('de'));
afterEach(() => {
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
  updateI18n({ locale: 'en', messages: {} });
});

it.each([
  ['en', 'de', 'Cancelled'],
  ['de', 'en', 'Abgesagt'],
])('UpcomingEvents speaks %s with no shared catalogue', async (locale, consoleLocale, label) => {
  page.props = { locale };
  updateI18n({ locale: consoleLocale, messages: {} });
  stubFetch({
    'GET /api/events/public/upcoming': { items: [item({ status: 'cancelled' })] },
  });
  const view = await mount(
    <UpcomingEventsRender
      heading="Coming up"
      calendars={[]}
      category=""
      count={5}
      layout="list"
      showImages={false}
    />,
  );
  await ready(view, 'li');
  expect(view.host.textContent).toContain(label);
});

it.each([
  ['en', 'de', 'Today'],
  ['de', 'en', 'Heute'],
])('EventsCalendar speaks %s with no shared catalogue', async (locale, consoleLocale, label) => {
  page.props = { locale };
  updateI18n({ locale: consoleLocale, messages: {} });
  stubFetch({
    'GET /api/events/public/calendars': {
      calendars: [
        {
          id: 'c1',
          slug: 'team',
          name: 'Team',
          color: '#2563eb',
          default_timezone: 'Europe/Vienna',
        },
      ],
      categories: [],
      default_timezone: 'Europe/Vienna',
    },
  });
  const view = await mount(
    <EventsCalendarRender calendars={[]} defaultView="month" height="medium" />,
  );
  await ready(view, '[role="toolbar"]');
  expect(view.host.textContent).toContain(label);
});
