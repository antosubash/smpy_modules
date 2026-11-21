// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { button, dialog, LIST, open, sub, text } from './subscriptions-dialog-support';
import { flush } from './support';
import { click, setValue } from './test-dom';

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  document.body.innerHTML = '';
});

describe('Subscription rows', () => {
  it('lists rows with the masked url, status, last update, count and skip reasons', async () => {
    const { view } = await open({ [`GET ${LIST}`]: [sub()] });
    expect(text()).toContain('Holidays');
    expect(text()).toContain('https://feeds.example.test/…');
    expect(text()).toContain('Up to date');
    expect(text()).toContain('214 events');
    expect(text()).toContain('12 events left out');
    expect(text()).toContain('unknown time zone (10), unsupported repeat rule (2)');
    expect(text()).toContain('Last updated');
    await view.unmount();
  });

  it('a paused row offers Resume, cannot be refreshed and shows no next update', async () => {
    const { calls, view } = await open({
      [`GET ${LIST}`]: [sub({ status: 'paused' })],
      'POST /api/events/subscriptions/s1/resume': () => Response.json(sub()),
      'POST /api/events/subscriptions/s1/pause': () => Response.json(sub({ status: 'paused' })),
    });
    expect(button('Pause')).toBeUndefined();
    expect((button('Refresh now') as HTMLButtonElement).disabled).toBe(true);
    expect(text()).not.toContain('Next update');
    await click(button('Resume') as HTMLElement);
    await flush(50);
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/resume'))).toBe(true);
    expect(calls.some((c) => c.url.endsWith('/pause'))).toBe(false);
    await view.unmount();
  });

  it('a running row offers Pause and shows the next update', async () => {
    const { view } = await open({ [`GET ${LIST}`]: [sub()] });
    expect(button('Resume')).toBeUndefined();
    expect((button('Refresh now') as HTMLButtonElement).disabled).toBe(false);
    expect(text()).toContain('Next update');
    await view.unmount();
  });

  it('says when a subscription may use internal addresses, and only then', async () => {
    const { view } = await open({
      [`GET ${LIST}`]: [
        sub({ may_use_internal_addresses: true }),
        sub({ id: 's2', label: 'Other' }),
      ],
    });
    expect(text().match(/May use internal addresses/g)).toHaveLength(1);
    await view.unmount();
  });

  it('counts one event in the singular', async () => {
    const { view } = await open({ [`GET ${LIST}`]: [sub({ item_count: 1, last_counts: {} })] });
    expect(text()).toContain('1 event');
    expect(text()).not.toContain('1 events');
    await click(button('Remove') as HTMLElement);
    await flush(20);
    expect(document.body.textContent).toContain('Its 1 cached event disappears');
    await view.unmount();
  });

  it('says so when a refresh is only queued', async () => {
    const { view } = await open({
      [`GET ${LIST}`]: [sub()],
      'POST /api/events/subscriptions/s1/refresh': () =>
        Response.json(sub({ status: 'pending', queued: true, queued_minutes: 2 }), { status: 202 }),
    });
    expect(document.querySelector('[data-testid="subscription-queued"]')).toBeNull();
    await click(button('Refresh now') as HTMLElement);
    await flush(50);
    expect(text()).toContain('Queued: it will refresh within about 2 minutes.');
    await view.unmount();
  });

  it('words a missing publish right as a subscription, not an event', async () => {
    const { view } = await open({
      [`GET ${LIST}`]: [sub()],
      'POST /api/events/subscriptions/s1/pause': () =>
        Response.json({ detail: 'x', code: 'subscription_publish_required' }, { status: 403 }),
    });
    await click(button('Pause') as HTMLElement);
    await flush(50);
    expect(text()).toContain(
      'Showing a subscription on public pages needs the publish permission.',
    );
    await view.unmount();
  });

  it('has no count sentence for a subscription that cached nothing', async () => {
    const { view } = await open({ [`GET ${LIST}`]: [sub({ item_count: 0, last_counts: {} })] });
    await click(button('Remove') as HTMLElement);
    await flush(20);
    expect(document.body.textContent).not.toContain('0 cached');
    expect(document.body.textContent).toContain('Nothing is cached yet.');
    await view.unmount();
  });

  it('shows the refresh_too_soon message for a 429', async () => {
    const { view } = await open({
      [`GET ${LIST}`]: [sub()],
      'POST /api/events/subscriptions/s1/refresh': () =>
        Response.json({ detail: 'soon', code: 'refresh_too_soon' }, { status: 429 }),
    });
    await click(button('Refresh now') as HTMLElement);
    await flush(50);
    expect(text()).toContain('refreshed a moment ago');
    await view.unmount();
  });

  it('shows a stored failure code in words, with the status for http_status', async () => {
    const { view } = await open({
      [`GET ${LIST}`]: [sub({ status: 'error', error_code: 'http_status', last_http_status: 503 })],
    });
    expect(text()).toContain('The server answered with status 503.');
    expect(text()).toContain('Failing');
    await view.unmount();
  });

  it('confirms a delete with the item count', async () => {
    const { calls, view } = await open({
      [`GET ${LIST}`]: [sub()],
      'DELETE /api/events/subscriptions/s1': null,
    });
    await click(button('Remove') as HTMLElement);
    await flush(20);
    expect(document.body.textContent).toContain(
      'Its 214 cached events disappear from the calendar.',
    );
    const confirm = [...document.querySelectorAll('button')].filter(
      (b) => b.textContent === 'Remove',
    );
    await click(confirm[confirm.length - 1] as HTMLElement);
    await flush(50);
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
    await view.unmount();
  });

  it.each([
    'url_invalid',
    'url_scheme',
    'url_userinfo',
    'url_port',
    'url_unreachable',
    'url_own_feed',
  ])('renders the message of the refusal %s', async (code) => {
    const { view } = await open({
      [`GET ${LIST}`]: [],
      [`POST ${LIST}`]: () => Response.json({ detail: 'x', code }, { status: 422 }),
    });
    await click(button('Add a subscription') as HTMLElement);
    await setValue(
      document.getElementById('events-sub-url') as HTMLInputElement,
      'https://x.example/a.ics',
    );
    await setValue(document.getElementById('events-sub-label') as HTMLInputElement, 'X');
    await click(button('Save') as HTMLElement);
    await flush(50);
    const alert = dialog()?.querySelector('form [role="alert"]')?.textContent ?? '';
    expect(alert).not.toBe('');
    expect(alert).not.toContain('events.subscriptions');
    expect(alert).not.toContain('x.example');
    await view.unmount();
  });
});
