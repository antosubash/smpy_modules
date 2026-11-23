// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import type { CreatedFeedToken } from '../utils/api-feeds';
import { flush, stubFetch } from './support';
import { click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { useFeedTokens } = await import('../hooks/useFeedTokens');

const LIST = '/api/events/calendars/c1/feed-tokens';
const SECRET = `evf_${'H'.repeat(43)}`;
const row = {
  id: 't2',
  label: 'Laptop',
  locale: 'en',
  created_at: '2026-11-01T10:00:00Z',
  last_used_at: null,
  user_id: 'u1',
  user_name: null,
  mine: true,
};

let seen: unknown = null;
let made: CreatedFeedToken | null = null;
function Probe({ open = true }: { open?: boolean }) {
  const state = useFeedTokens('c1', open, false);
  seen = state;
  return (
    <button
      type="button"
      onClick={() => {
        void state.create({ label: 'Laptop', locale: null }).then((link) => {
          made = link;
        });
      }}
    >
      Create
    </button>
  );
}
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
  seen = made = null;
});

it('create does not cache the secret in the list state', async () => {
  let reads = 0;
  stubFetch({
    [`GET ${LIST}`]: () => (++reads === 1 ? [] : [row]),
    [`POST ${LIST}`]: () =>
      Response.json(
        { ...row, url: `https://x/events/feed/${SECRET}.ics`, webcal_url: `webcal://x/${SECRET}` },
        { status: 201 },
      ),
  });
  const view = await mount(<Probe />);
  await flush();
  await click(view.button('Create'));
  await flush();
  expect(made?.url).toContain(SECRET); // handed to the caller once
  expect(JSON.stringify(seen)).not.toContain(SECRET); // and not kept in the hook's state
  expect((seen as { mine: unknown[] }).mine).toEqual([row]);
  await view.unmount();
});

it('is idle while closed and never reads after closing mid-request', async () => {
  const calls = stubFetch({ [`GET ${LIST}`]: [] });
  const view = await mount(<Probe open={false} />);
  await flush();
  expect(calls).toHaveLength(0);
  await view.unmount();
});
