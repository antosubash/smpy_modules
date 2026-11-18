// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { calendar, flush, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast }));

const { SubscribeDialog } = await import('../components/feeds/SubscribeDialog');

const LIST = '/api/events/calendars/c1/feed-tokens';
const SECRET = `evf_${'S'.repeat(43)}`;
const row = (over = {}) => ({
  id: 't1',
  label: 'Phone',
  locale: 'en',
  created_at: '2026-11-01T10:00:00Z',
  last_used_at: null,
  user_id: 'u1',
  user_name: 'Olga Owner',
  mine: true,
  ...over,
});
const created = {
  ...row({ id: 't2', label: 'Laptop' }),
  url: `https://example.org/events/feed/${SECRET}.ics`,
  webcal_url: `webcal://example.org/events/feed/${SECRET}.ics`,
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  document.body.innerHTML = '';
});

type Props = Partial<Parameters<typeof SubscribeDialog>[0]>;
async function open(routes: Record<string, unknown>, props: Props = {}) {
  const calls = stubFetch(routes);
  const view = await mount(
    <SubscribeDialog
      calendar={calendar(props.calendar)}
      canManage={false}
      contentLocales={['en']}
      publicPrefix="/events"
      {...props}
    />,
  );
  await click(view.find('[data-testid="events-subscribe"]'));
  await flush(50);
  return { calls, view };
}
const dialog = () => document.querySelector('[data-testid="events-subscribe-dialog"]');
const text = () => dialog()?.textContent ?? '';
const button = (label: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.includes(label));

async function create(label = 'Laptop') {
  await setValue(document.getElementById('events-feed-label') as HTMLInputElement, label);
  await click(button('Create a private link'));
  await flush(50);
}

describe('SubscribeDialog', () => {
  it('shows a public calendar’s feed first', async () => {
    const { view } = await open(
      { [`GET ${LIST}`]: [] },
      { calendar: calendar({ visibility: 'public', slug: 'team' }) },
    );
    const feed = dialog()?.querySelector<HTMLInputElement>('input[readonly]');
    expect(feed?.value).toMatch(/\/events\/c\/team\.ics$/);
    expect(dialog()?.querySelector('a[href^="webcal:"]')).not.toBeNull();
    expect(text().indexOf('Calendar link (https)')).toBeLessThan(text().indexOf('Private link'));
    await view.unmount();
  });

  it('shows only the private section for a private calendar', async () => {
    const { view } = await open({ [`GET ${LIST}`]: [] });
    expect(text()).toContain('Private link');
    expect(text()).not.toContain('Calendar link (https)');
    expect(dialog()?.querySelector('a[href^="webcal:"]')).toBeNull();
    await view.unmount();
  });

  it('shows the new link once and not again after closing', async () => {
    let made = false;
    const { calls, view } = await open({
      [`GET ${LIST}`]: () => (made ? [row({ id: 't2', label: 'Laptop' })] : []),
      [`POST ${LIST}`]: () => {
        made = true;
        return Response.json(created, { status: 201 });
      },
    });
    await create();
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.body).toEqual({ label: 'Laptop', locale: null });
    const link = dialog()?.querySelector<HTMLInputElement>('input[readonly]');
    expect(link?.value).toBe(created.url);
    expect(text()).toContain('You will not see this link again');
    expect(text()).toContain('Laptop'); // the list re-read, with no link
    // Never in the address bar, storage or a toast.
    expect(location.href).not.toContain(SECRET);
    expect(JSON.stringify({ ...localStorage })).not.toContain(SECRET);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(SECRET);
    expect(JSON.stringify(toast.mock.calls)).not.toContain(SECRET);
    // Close and reopen: the list shows the label and nothing opens it.
    await click(button('Close'));
    await flush(50);
    await click(view.find('[data-testid="events-subscribe"]'));
    await flush(50);
    expect(text()).toContain('Laptop');
    expect(text()).not.toContain('You will not see this link again');
    expect(text()).not.toContain(SECRET);
    expect(document.body.innerHTML).not.toContain(SECRET);
    await view.unmount();
  });

  it('copies the url', async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    const { view } = await open({
      [`GET ${LIST}`]: [],
      [`POST ${LIST}`]: () => Response.json(created, { status: 201 }),
    });
    await create();
    await click(button('Copy link'));
    expect(writeText).toHaveBeenCalledWith(created.url);
    expect(text()).toContain('Link copied');
    await view.unmount();
  });

  it('still shows a selectable link when the clipboard is refused', async () => {
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText: async () => {
          throw new Error('denied');
        },
      },
    });
    const { view } = await open({
      [`GET ${LIST}`]: [],
      [`POST ${LIST}`]: () => Response.json(created, { status: 201 }),
    });
    await create();
    await click(button('Copy link'));
    expect(dialog()?.querySelector<HTMLInputElement>('input[readonly]')?.value).toBe(created.url);
    expect(text()).not.toContain('Link copied');
    await view.unmount();
  });

  it('asks before revoking, then removes the link', async () => {
    let revoked = false;
    const { calls, view } = await open({
      [`GET ${LIST}`]: () => (revoked ? [] : [row()]),
      'DELETE /api/events/feed-tokens/t1': () => {
        revoked = true;
        return null;
      },
    });
    expect(text()).toContain('Phone');
    expect(text()).toContain('never');
    await click(document.querySelector('[aria-label="Revoke Phone"]'));
    await flush(50);
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false); // asked first
    expect(document.body.textContent).toContain('Revoke Phone?');
    await click(
      [...document.querySelectorAll('[role="alertdialog"] button')].find(
        (b) => b.textContent === 'Revoke',
      ),
    );
    await flush(50);
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
    expect(text()).not.toContain('Phone');
    await view.unmount();
  });

  it('shows the limit message', async () => {
    const { view } = await open({
      [`GET ${LIST}`]: [],
      [`POST ${LIST}`]: () => Response.json({ detail: 'x', code: 'token_limit' }, { status: 409 }),
    });
    await create();
    expect(text()).toContain('You already have the most private links');
    expect(dialog()?.querySelector('input[readonly]')).toBeNull();
    await view.unmount();
  });

  it('offers the language when the site has several', async () => {
    const { calls, view } = await open(
      {
        [`GET ${LIST}`]: [],
        [`POST ${LIST}`]: () => Response.json(created, { status: 201 }),
      },
      { contentLocales: ['en', 'de'] },
    );
    const select = document.getElementById('events-feed-locale') as HTMLSelectElement;
    expect([...select.options].map((o) => [o.value, o.textContent])).toEqual([
      ['en', 'English'],
      ['de', 'Deutsch'],
    ]);
    await setValue(select, 'de');
    await create();
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ label: 'Laptop', locale: 'de' });
    await view.unmount();
  });

  it('shows everyone’s links only to managers, naming nobody it was not told', async () => {
    const everyone = [
      row({ id: 't9', label: 'Theirs', user_id: 'u9', user_name: null, mine: false }),
    ];
    const routes = {
      [`GET ${LIST}`]: (call: { url: string }) => (call.url.includes('all=true') ? everyone : []),
    };
    const plain = await open(routes);
    expect(button('Everyone’s links')).toBeUndefined();
    await plain.view.unmount();
    document.body.innerHTML = '';

    const { calls, view } = await open(routes, { canManage: true });
    expect(calls.some((c) => c.url.endsWith('all=true'))).toBe(true);
    await click(button('Everyone’s links'));
    expect(text()).toContain('Theirs');
    expect(text()).toContain('Unknown user');
    expect(text()).not.toContain('u9');
    expect(text()).toContain('Theirs · English · Created 1 Nov 2026'); // not "en", not US dates
    await view.unmount();
  });

  it('asks for nothing while closed', async () => {
    const calls = stubFetch({ [`GET ${LIST}`]: [] });
    const view = await mount(
      <SubscribeDialog
        calendar={calendar()}
        canManage={false}
        contentLocales={['en']}
        publicPrefix="/events"
      />,
    );
    await flush(50);
    expect(calls).toHaveLength(0);
    await view.unmount();
  });
});
