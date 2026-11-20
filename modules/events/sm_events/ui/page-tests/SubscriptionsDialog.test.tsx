// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { calendar, flush, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast }));

const { SubscriptionsDialog } = await import('../components/subscriptions/SubscriptionsDialog');

const LIST = '/api/events/calendars/c1/subscriptions';
const sub = (over = {}) => ({
  id: 's1',
  calendar_id: 'c1',
  url_display: 'https://feeds.example.test/…',
  label: 'Holidays',
  color: null,
  refresh_minutes: null,
  effective_refresh_minutes: 60,
  public: false,
  status: 'ok',
  error_code: null,
  last_http_status: null,
  last_fetched_at: '2026-11-19T10:00:00Z',
  last_ok_at: '2026-11-19T10:00:00Z',
  next_fetch_at: '2026-11-19T11:00:00Z',
  consecutive_failures: 0,
  item_count: 214,
  last_counts: { stored: 214, skipped: 12, reasons: { unknown_timezone: 10, unsupported_rule: 2 } },
  may_use_internal_addresses: false,
  version: 'v1',
  ...over,
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  document.body.innerHTML = '';
});

type Props = Partial<Parameters<typeof SubscriptionsDialog>[0]>;
async function open(routes: Record<string, unknown>, props: Props = {}) {
  const calls = stubFetch(routes);
  const view = await mount(
    <SubscriptionsDialog
      calendar={calendar(props.calendar)}
      canPublish={false}
      defaultMinutes={60}
      {...props}
    />,
  );
  await click(view.find('[data-testid="events-subscriptions"]'));
  await flush(50);
  return { calls, view };
}
const dialog = () => document.querySelector('[data-testid="events-subscriptions-dialog"]');
const text = () => dialog()?.textContent ?? '';
const button = (label: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.includes(label));

describe('SubscriptionsDialog', () => {
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

  it('adds a subscription and clears the address field', async () => {
    let made = false;
    const { calls, view } = await open({
      [`GET ${LIST}`]: () => (made ? [sub()] : []),
      [`POST ${LIST}`]: () => {
        made = true;
        return Response.json(sub(), { status: 201 });
      },
    });
    await click(button('Add a subscription') as HTMLElement);
    const url = document.getElementById('events-sub-url') as HTMLInputElement;
    expect(url.type).toBe('url');
    expect(url.autocomplete).toBe('off');
    expect(text()).toContain('stored encrypted and never shown again');
    await setValue(url, 'https://feeds.example.test/private/SECRET/basic.ics');
    await setValue(document.getElementById('events-sub-label') as HTMLInputElement, 'Holidays');
    await click(button('Save') as HTMLElement);
    await flush(50);
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.body).toMatchObject({
      url: 'https://feeds.example.test/private/SECRET/basic.ics',
      label: 'Holidays',
      public: false,
    });
    expect(document.getElementById('events-sub-url')).toBeNull(); // the form closed
    expect(text()).not.toContain('SECRET'); // and nothing shows the address again
    await view.unmount();
  });

  it('edit leaves the address empty and omits it from the patch unless typed', async () => {
    const { calls, view } = await open({
      [`GET ${LIST}`]: [sub()],
      'PATCH /api/events/subscriptions/s1': () => Response.json(sub({ label: 'Renamed' })),
    });
    await click(button('Edit') as HTMLElement);
    const url = document.getElementById('events-sub-url') as HTMLInputElement;
    expect(url.value).toBe('');
    expect(url.placeholder).toContain('Leave empty to keep the current address');
    await setValue(document.getElementById('events-sub-label') as HTMLInputElement, 'Renamed');
    await click(button('Save') as HTMLElement);
    await flush(50);
    const patch = calls.find((c) => c.method === 'PATCH');
    expect(patch?.body).toEqual({ expected: 'v1', label: 'Renamed' });
    await view.unmount();
  });

  it('the public toggle needs a public calendar and the publish permission', async () => {
    const cases: [boolean, string, boolean][] = [
      [false, 'public', true],
      [true, 'private', true],
      [true, 'public', false],
    ];
    for (const [canPublish, visibility, disabled] of cases) {
      const { view } = await open(
        { [`GET ${LIST}`]: [] },
        { canPublish, calendar: calendar({ visibility }) },
      );
      await click(button('Add a subscription') as HTMLElement);
      const box = document.getElementById('events-sub-public') as HTMLInputElement;
      expect(box.disabled, `${canPublish} ${visibility}`).toBe(disabled);
      await view.unmount();
      document.body.innerHTML = '';
    }
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
