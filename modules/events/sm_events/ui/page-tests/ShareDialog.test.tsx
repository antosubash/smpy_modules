// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flush, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const { ShareDialog } = await import('../components/share/ShareDialog');

const SHARES = '/api/sharing/shares';
const CANDIDATES = '/api/events/calendars/c1/share-candidates';
const sam = { id: 'u2', display_name: 'Sam Smith', email: 's***@example.com' };
const share = {
  id: 's1',
  subject_id: 'u3',
  subject_label: 'Kim Kirk',
  role: 'view',
  expired: false,
};

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

async function search(q: string) {
  const input = document.querySelector<HTMLInputElement>('#events-share-search');
  if (input) await setValue(input, q);
  await flush(300);
}

async function open(routes: Record<string, unknown>, q = 'sam') {
  const calls = stubFetch(routes);
  const view = await mount(<ShareDialog calendarId="c1" />);
  await click(view.find('[data-testid="events-share"]'));
  await flush(300);
  if (q) await search(q);
  return { calls, view };
}

const dialog = () => document.querySelector('[data-testid="events-share-dialog"]');

describe('ShareDialog', () => {
  it('lists the current shares of this calendar by the canonical resource id', async () => {
    const { calls, view } = await open({
      [`GET ${SHARES}`]: [share],
      [`GET ${CANDIDATES}`]: [sam],
    });
    const list = calls.find((c) => c.url.startsWith(SHARES));
    expect(list?.url).toBe(`${SHARES}?resource_type=events.calendar&resource_id=c1`);
    expect(dialog()?.textContent).toContain('Kim Kirk');
    expect(dialog()?.textContent).toContain('s***@example.com');
    await view.unmount();
  });

  it('does not offer someone who already holds a share', async () => {
    const holder = { id: 'u3', display_name: 'Kim Kirk', email: 'kim@example.com' };
    const { view } = await open({
      [`GET ${SHARES}`]: [share],
      [`GET ${CANDIDATES}`]: [sam, holder],
    });
    const names = [...document.querySelectorAll('[data-testid="events-share-candidate"]')].map(
      (n) => n.textContent,
    );
    expect(names).toHaveLength(1);
    expect(names[0]).toContain('Sam Smith');
    await view.unmount();
  });

  it.each(['view', 'edit'])('grants %s and re-reads the shares', async (chosen) => {
    let granted = false;
    const { calls, view } = await open({
      [`GET ${SHARES}`]: () =>
        granted
          ? [
              share,
              { ...share, id: 's2', subject_id: 'u2', subject_label: 'Sam Smith', role: chosen },
            ]
          : [share],
      [`GET ${CANDIDATES}`]: [sam],
      [`POST ${SHARES}`]: () => {
        granted = true;
        return { ...share, id: 's2', subject_id: 'u2', role: chosen };
      },
    });
    const role = document.querySelector<HTMLSelectElement>('#events-share-role');
    if (role) {
      const { setValue } = await import('./test-dom');
      await setValue(role, chosen);
    }
    await click(document.querySelector('[data-testid="events-share-candidate"] button'));
    await flush(20);
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.body).toEqual({
      resource_type: 'events.calendar',
      resource_id: 'c1',
      subject_id: 'u2',
      role: chosen,
    });
    expect(dialog()?.textContent).toContain(`Sam Smith · Can ${chosen}`);
    await view.unmount();
  });

  it('does not search below three characters, and says so', async () => {
    const { calls, view } = await open({ [`GET ${SHARES}`]: [], [`GET ${CANDIDATES}`]: [sam] }, '');
    const hint = () => document.querySelector('[data-testid="events-share-hint"]');
    expect(hint()?.textContent).toBe('Type at least 3 characters to search.');
    await search('sa');
    expect(hint()).not.toBeNull();
    expect(calls.some((c) => c.url.startsWith(CANDIDATES))).toBe(false);
    await search('sam');
    expect(hint()).toBeNull();
    const asked = calls.filter((c) => c.url.startsWith(CANDIDATES));
    expect(asked.map((c) => c.url)).toEqual([`${CANDIDATES}?q=sam`]);
    expect(document.querySelectorAll('[data-testid="events-share-candidate"]')).toHaveLength(1);
    await view.unmount();
  });

  it('clears a failed search once the query is too short to search', async () => {
    const { view } = await open({
      [`GET ${SHARES}`]: [],
      [`GET ${CANDIDATES}`]: () => {
        throw new Error('offline');
      },
    });
    const alert = () =>
      document.querySelector('[data-testid="events-share-dialog"] [role="alert"]');
    expect(alert()).not.toBeNull();
    await search('sa');
    expect(alert()).toBeNull();
    await view.unmount();
  });

  it('revokes a share by its id', async () => {
    const { calls, view } = await open({
      [`GET ${SHARES}`]: [share],
      [`GET ${CANDIDATES}`]: [],
      [`DELETE ${SHARES}/s1`]: null,
    });
    await click(document.querySelector('[data-testid="events-share-row"] button'));
    await flush(20);
    expect(calls.some((c) => c.method === 'DELETE' && c.url === `${SHARES}/s1`)).toBe(true);
    await view.unmount();
  });
});
