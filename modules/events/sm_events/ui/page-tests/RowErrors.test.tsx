// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { button, calendar, flush, stubFetch } from './support';
import { click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
const { toast } = await import('sonner');
const { default: Calendars } = await import('../../pages/Calendars');
const API = '/api/events/calendars';
const props = { can_create: true, can_manage: false, user_id: 'u1', default_timezone: 'UTC' };
const GONE = 'This calendar no longer exists.';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(toast.error).mockClear();
  document.body.innerHTML = '';
});

const invalid = (status: number, detail: unknown) => Response.json({ detail }, { status });

describe('calendar rows after another tab acted', () => {
  const listing = (trash: unknown[], active: unknown[]) => ({
    [`GET ${API}`]: (call: { url: string }) => (call.url.includes('trashed=true') ? trash : active),
  });
  async function trashTab(routes: Record<string, unknown>) {
    const calls = stubFetch(routes);
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Trash'));
    await flush();
    return { view, calls };
  }
  it('restoring what is already restored is silent and reloads', async () => {
    const { view, calls } = await trashTab({
      ...listing([calendar()], [calendar()]),
      [`POST ${API}/c1/restore`]: invalid(404, 'Not found'),
    });
    await click(button('Restore'));
    await flush();
    expect(toast.error).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain(GONE);
    expect(calls.filter((c) => c.url.includes('trashed=true')).length).toBeGreaterThan(1);
    await view.unmount();
  });
  it('restoring a calendar that is in neither list says it is gone', async () => {
    let trash: unknown[] = [calendar()];
    const { view } = await trashTab({
      ...listing(trash, []),
      [`GET ${API}`]: (call: { url: string }) => (call.url.includes('trashed=true') ? trash : []),
      [`POST ${API}/c1/restore`]: () => {
        trash = [];
        return invalid(404, 'Not found');
      },
    });
    await click(button('Restore'));
    await flush();
    expect(toast.error).toHaveBeenCalledWith(GONE);
    await view.unmount();
  });
  it('trashing what is already in the trash closes the confirmation, silently', async () => {
    let trashed = false;
    stubFetch({
      [`GET ${API}`]: (call: { url: string }) =>
        call.url.includes('trashed=true')
          ? trashed
            ? [calendar()]
            : []
          : trashed
            ? []
            : [calendar()],
      [`DELETE ${API}/c1`]: () => {
        trashed = true;
        return invalid(404, 'Not found');
      },
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Move to trash'));
    const confirm = document.querySelector('[role="alertdialog"]');
    await click(
      [...(confirm?.querySelectorAll('button') ?? [])].find(
        (b) => b.textContent === 'Move to trash',
      ) ?? null,
    );
    await flush();
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
    expect(toast.error).not.toHaveBeenCalled();
    await view.unmount();
  });
});

describe('names are isolated', () => {
  it('wraps a calendar name and its owner in bdi', async () => {
    stubFetch({ [`GET ${API}`]: [calendar({ name: '‮evil', owner_id: 'u9', owner_name: 'Ola' })] });
    const view = await mount(<Calendars {...props} />);
    await flush();
    const cells = [...view.host.querySelectorAll('td bdi')].map((b) => b.textContent);
    expect(cells).toContain('‮evil');
    expect(cells).toContain('Ola');
    await view.unmount();
  });
});
