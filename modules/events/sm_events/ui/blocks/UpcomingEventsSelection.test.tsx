// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { item } from '../page-tests/public-support';
import { flush, stubFetch } from '../page-tests/support';
import { mount, ready, settle } from '../page-tests/test-dom';
import type { PublicListItem } from '../public/types';

const page = { props: {} as Record<string, unknown> };
vi.mock('@inertiajs/react', () => ({ usePage: () => ({ props: page.props }) }));

const { UpcomingEventsBlock } = await import('./UpcomingEventsBlock');
const { UpcomingEventsRender } = await import('./UpcomingEventsRender');

const UPCOMING = 'GET /api/events/public/upcoming';
const CALENDARS = 'GET /api/events/public/calendars';
const base = {
  heading: 'Coming up',
  calendars: [],
  category: '',
  count: 5,
  layout: 'list' as const,
  showImages: true,
};

type Rendered = Parameters<typeof UpcomingEventsRender>[0];
const render = (props: Partial<Rendered> = {}) => <UpcomingEventsRender {...base} {...props} />;

beforeEach(() => {
  page.props = { locale: 'en' };
});
afterEach(() => {
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('UpcomingEvents selection', () => {
  it('a calendar selection that cannot be read shows nothing and asks for nothing', async () => {
    const calls = stubFetch({
      [UPCOMING]: { items: [item()] },
      [CALENDARS]: { calendars: [], categories: [], default_timezone: 'UTC' },
    });
    for (const calendars of ['team', ['team'], [null], [{ name: 'x' }], [{ slug: 7 }], 5, {}]) {
      const view = await mount(render({ calendars: calendars as never }));
      await settle();
      expect(view.host.innerHTML, JSON.stringify(calendars)).toBe('');
      await view.unmount();
    }
    expect(calls.filter((c) => c.url.includes('/upcoming'))).toEqual([]); // never "every calendar"
  });

  it('tells the editor the selection could not be read', async () => {
    stubFetch({ [UPCOMING]: { items: [item()] } });
    const view = await mount(
      render({ calendars: 'team' as never, puck: { isEditing: true } } as never),
    );
    await settle();
    expect(view.host.textContent).toContain('could not be read');
  });
});
