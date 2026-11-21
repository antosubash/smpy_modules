// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { button, calendar, field, flush, stubFetch, submit } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: Calendars } = await import('../../pages/Calendars');
const API = '/api/events/calendars';
const props = { can_create: false, can_manage: true, user_id: 'u1', default_timezone: 'UTC' };
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

it('sets visibility through its dedicated endpoint', async () => {
  const calls = stubFetch({
    [`GET ${API}`]: [calendar()],
    [`PUT ${API}/c1/visibility`]: calendar({ visibility: 'public' }),
  });
  const view = await mount(<Calendars {...props} />);
  await flush();
  await click(button('Visibility'));
  await setValue(field('visibility-value'), 'public');
  await submit();
  expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ visibility: 'public' });
  await view.unmount();
});
it('only managers can transfer to a picked active member, preserving masked email', async () => {
  const calls = stubFetch({
    [`GET ${API}`]: [calendar()],
    [`GET ${API}/c1/share-candidates`]: [
      { id: 'u2', display_name: 'Sam', email: 's***@example.org' },
    ],
    [`PUT ${API}/c1/owner`]: calendar({ owner_id: 'u2' }),
  });
  const view = await mount(<Calendars {...props} />);
  await flush();
  await click(button('Transfer ownership'));
  await setValue(field('owner-search'), 'sam');
  await flush(300);
  expect(document.querySelector('[role="dialog"]')?.textContent).toContain('s***@example.org');
  await click(button('Select Sam'));
  await submit();
  expect(calls.find((c) => c.url === `${API}/c1/owner`)?.body).toEqual({ owner_id: 'u2' });
  await view.unmount();
});
it('keeps an owner transfer open on owner_not_allowed', async () => {
  stubFetch({
    [`GET ${API}`]: [calendar()],
    [`GET ${API}/c1/share-candidates`]: [
      { id: 'u2', display_name: 'Sam', email: 's***@example.org' },
    ],
    [`PUT ${API}/c1/owner`]: Response.json({ code: 'owner_not_allowed' }, { status: 422 }),
  });
  const view = await mount(<Calendars {...props} />);
  await flush();
  await click(button('Transfer ownership'));
  await setValue(field('owner-search'), 'sam');
  await flush(300);
  await click(button('Select Sam'));
  await submit();
  expect(document.querySelector('[role="alert"]')?.textContent).toContain('active member');
  await view.unmount();
});
