// @vitest-environment happy-dom
// biome-ignore-all lint/correctness/noComponentHookFactories: plugin loaders are test doubles

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { resetReported } from '../extensions/PluginBoundary';
import { clearExtensions, registerEventType } from '../extensions/registry';
import type { PublicDetailProps } from '../extensions/types';
import type { PublicEventProps } from '../public/types';
import { headValues } from './public-support';
import { flush, NO_REGISTRATION } from './support';
import { mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: PublicEvent } = await import('../../pages/PublicEvent');

function props(overrides: Partial<PublicEventProps> = {}): PublicEventProps {
  return {
    type: 'acme:talk',
    public_extra: { speaker: 'Ada <b>Lovelace</b>' },
    locale: 'en',
    title: 'Talk',
    summary: null,
    description_tree: [],
    timezone: 'UTC',
    all_day: false,
    when: null,
    series: null,
    cancelled: false,
    place: {
      mode: 'in_person',
      venue_name: null,
      address: null,
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
    registration_url: null,
    registration: NO_REGISTRATION,
    ics_url: '/events/talk.ics',
    canonical_url: 'https://x.example/events/talk',
    alternates: [],
    json_ld: null,
    index_in_search: true,
    head: headValues('Talk'),
    ...overrides,
  };
}

let received: PublicDetailProps | null = null;
function Detail(p: PublicDetailProps) {
  received = p;
  return <div data-testid="public-detail">{String(p.publicExtra.speaker)}</div>;
}

beforeEach(() => {
  clearExtensions();
  resetReported();
  received = null;
});
afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

it("renders the plugin's PublicDetail with publicExtra only, as text", async () => {
  registerEventType({ id: 'acme:talk', PublicDetail: async () => ({ default: Detail }) });
  const view = await mount(<PublicEvent {...props()} />);
  await flush();
  const node = document.querySelector('[data-testid="public-detail"]');
  expect(node?.textContent).toBe('Ada <b>Lovelace</b>'); // text, never markup
  expect(node?.querySelector('b')).toBeNull();
  expect(received?.publicExtra).toEqual({ speaker: 'Ada <b>Lovelace</b>' });
  expect(received?.locale).toBe('en');
  expect(received?.event?.type).toBe('acme:talk');
  expect(Object.keys(received ?? {}).sort()).toEqual([
    'event',
    'locale',
    'occurrence',
    'publicExtra',
  ]);
  await view.unmount();
});

it('renders nothing for a type with no registration, and the page still renders', async () => {
  const view = await mount(<PublicEvent {...props({ type: 'gone:thing', public_extra: {} })} />);
  await flush();
  expect(document.querySelector('[data-testid="public-detail"]')).toBeNull();
  expect(document.querySelector('h1')?.textContent).toBe('Talk');
  await view.unmount();
});

it('a rejected lazy import renders nothing and the page still renders', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  registerEventType({ id: 'acme:talk', PublicDetail: () => Promise.reject(new Error('chunk')) });
  const view = await mount(<PublicEvent {...props()} />);
  await flush();
  expect(document.querySelector('[data-testid="public-detail"]')).toBeNull();
  expect(document.querySelector('h1')?.textContent).toBe('Talk');
  await view.unmount();
});

it('a component that throws while rendering renders nothing', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  registerEventType({
    id: 'acme:talk',
    PublicDetail: async () => ({
      default: () => {
        throw new Error('boom');
      },
    }),
  });
  const view = await mount(<PublicEvent {...props()} />);
  await flush();
  expect(document.querySelector('h1')?.textContent).toBe('Talk');
  expect(document.body.textContent).not.toContain('boom');
  expect(document.body.textContent).not.toMatch(/extension|failed/i); // nothing on public pages
  await view.unmount();
});
