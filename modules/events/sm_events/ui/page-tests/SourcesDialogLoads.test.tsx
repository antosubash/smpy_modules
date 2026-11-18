// @vitest-environment happy-dom
import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { resetLoader } from '../extensions/load';
import { clearExtensions } from '../extensions/registry';
import { calendar, flush, stubFetch } from './support';
import { click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: Calendars } = await import('../../pages/Calendars');

beforeEach(() => {
  clearExtensions();
  resetLoader();
});
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

it('loads the plugins itself: the Calendars screen has no calendar to do it', async () => {
  stubFetch({
    'GET /api/events/calendars': [
      calendar({
        sources: [{ id: 'records:dates', settings: {}, installed: true, label_key: null }],
      }),
    ],
    'GET /api/events/sources': [
      {
        id: 'records:dates',
        label_key: 'records.events.source.label',
        color: null,
        icon: 'database',
        public: true,
        has_settings: true,
        settings_schema: { type: 'object' },
      },
    ],
    'GET /api/records/types': { items: [] },
  });
  const view = await mount(
    <Calendars can_create={false} can_manage={false} user_id="u1" default_timezone="UTC" />,
  );
  await flush();
  await click(document.querySelector('button[aria-label^="Sources"]') as HTMLElement);
  await vi.waitFor(
    () =>
      expect(
        document.querySelector('[role="dialog"] [data-testid="records-mapping"]'),
      ).not.toBeNull(),
    { timeout: 5000 },
  );
  // records' own section (its mapping form), not the JSON fallback
  expect(document.querySelector('[role="dialog"] [data-testid="records-mapping"]')).not.toBeNull();
  expect(document.querySelector('[role="dialog"] textarea')).toBeNull();
  await view.unmount();
});
