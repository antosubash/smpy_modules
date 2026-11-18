// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { eventDetail, field, flush, refusal, stubFetch } from './support';
import { act, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { router } = await import('@inertiajs/react');
const { toast } = await import('sonner');
const { default: EventEditor } = await import('../../pages/EventEditor');
const API = '/api/events/events';
const props = {
  event_id: null as string | null,
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};

beforeEach(() => history.replaceState(null, '', '/admin/events/edit/new?calendar=c1'));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(router.visit).mockClear();
  vi.mocked(toast.success).mockClear();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
const submit = () =>
  act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });

describe('request lifetime', () => {
  it('a save that finishes after the page closed does nothing', async () => {
    const late = deferred<Response>();
    stubFetch({ [`POST ${API}`]: () => late.promise });
    const view = await mount(<EventEditor {...props} />);
    await setValue(field('text-en-title'), 'Concert');
    await submit();
    await view.unmount();
    late.resolve(Response.json(eventDetail({ id: 'new1' }), { status: 201 }));
    await flush();
    expect(router.visit).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('a failed late save shows nothing either', async () => {
    const late = deferred<Response>();
    stubFetch({ [`POST ${API}`]: () => late.promise });
    const view = await mount(<EventEditor {...props} />);
    await setValue(field('text-en-title'), 'Concert');
    await submit();
    await view.unmount();
    late.resolve(refusal(500, 'x'));
    await flush();
    expect(document.body.textContent).toBe('');
  });

  it('does not send a second save while one is in flight', async () => {
    const late = deferred<Response>();
    const calls = stubFetch({ [`POST ${API}`]: () => late.promise });
    const view = await mount(<EventEditor {...props} />);
    await setValue(field('text-en-title'), 'Concert');
    await submit();
    await submit();
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
    late.resolve(Response.json(eventDetail({ id: 'new1' }), { status: 201 }));
    await flush();
    await view.unmount();
  });
});

describe('error states', () => {
  const edit = { ...props, event_id: 'e1' };
  it('a rate limit on load says so, without a form or an empty state', async () => {
    stubFetch({
      [`GET ${API}/e1`]: () =>
        Response.json({ detail: 'slow', code: 'rate_limited', retry_after: 9 }, { status: 429 }),
    });
    const view = await mount(<EventEditor {...edit} />);
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toContain('Too many searches. Try again in 9');
    expect(view.find('form')).toBeNull();
    await view.unmount();
  });

  it('a 404 on save says the event is gone, not that something is stale', async () => {
    stubFetch({
      [`GET ${API}/e1`]: () => eventDetail({ revision: 2 }),
      [`PATCH ${API}/e1`]: () => refusal(404, 'not_found'),
    });
    const view = await mount(<EventEditor {...edit} />);
    await flush();
    await setValue(field('text-en-title'), 'Changed');
    await submit();
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toBe('This event no longer exists.');
    expect(view.host.textContent).not.toContain('changed this event');
    await view.unmount();
  });

  it('a forbidden save on a locked event names the publish right', async () => {
    stubFetch({
      [`GET ${API}/e1`]: () => eventDetail({ revision: 2 }),
      [`PATCH ${API}/e1`]: () => refusal(403, 'publish_required'),
    });
    const view = await mount(<EventEditor {...edit} />);
    await flush();
    await setValue(field('text-en-title'), 'Changed');
    await submit();
    await flush();
    expect(view.find('form [role="alert"]')?.textContent).toContain('Only a publisher can change');
    await view.unmount();
  });

  it('keeps the form and focus on a 429 save', async () => {
    stubFetch({
      [`GET ${API}/e1`]: () => eventDetail({ revision: 2 }),
      [`PATCH ${API}/e1`]: () =>
        Response.json({ detail: 'slow', code: 'rate_limited' }, { status: 429 }),
    });
    const view = await mount(<EventEditor {...edit} />);
    await flush();
    await setValue(field('text-en-title'), 'Changed');
    await submit();
    await flush();
    expect(view.find('form [role="alert"]')?.textContent).toContain('Too many');
    expect(field('text-en-title').value).toBe('Changed');
    await view.unmount();
  });
});
