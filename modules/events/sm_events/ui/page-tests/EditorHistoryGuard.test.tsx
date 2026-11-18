// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { eventDetail, field, flush, stubFetch } from './support';
import { act, click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
const { router } = await import('@inertiajs/react');
const API = '/api/events/events';
const props = {
  event_id: 'e1',
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en', 'de'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};
const TITLE = 'Leave without saving?';

let push: ReturnType<typeof vi.spyOn>;
let go: ReturnType<typeof vi.spyOn>;
let back: ReturnType<typeof vi.spyOn>;
/** Stands in for Inertia's own popstate handler: registered after the guard's. */
let inertia: ReturnType<typeof vi.fn>;

beforeEach(() => {
  push = vi.spyOn(window.history, 'pushState');
  go = vi.spyOn(window.history, 'go').mockImplementation(() => {});
  back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
  inertia = vi.fn();
});
afterEach(() => {
  vi.mocked(router.visit).mockClear();
  window.removeEventListener('popstate', inertia as EventListener);
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

async function open() {
  stubFetch({
    [`GET ${API}/e1`]: () => eventDetail({ revision: 4 }),
    [`PATCH ${API}/e1`]: () => eventDetail({ revision: 5 }),
  });
  const view = await mount(<EventEditor {...props} />);
  await flush();
  window.addEventListener('popstate', inertia as EventListener);
  return view;
}
/** The browser's Back button: the event is delivered while the form is mounted. */
const pressBack = () => act(async () => void window.dispatchEvent(new PopStateEvent('popstate')));
/** The dialog is portaled out of the page, so the view does not see it. */
const dialogButton = (text: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent === text);
const dirtyForm = () => setValue(field('text-en-title'), 'Changed');
const submit = async () => {
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
};

describe('the browser Back button', () => {
  it('is not intercepted while the form is clean', async () => {
    const view = await open();
    await pressBack();
    expect(inertia).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain(TITLE);
    expect(push).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('asks before leaving, and never reaches Inertia while it asks', async () => {
    const view = await open();
    await dirtyForm();
    expect(push).toHaveBeenCalledTimes(1); // the sentinel entry
    await pressBack();
    expect(inertia).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(TITLE);
    expect(push).toHaveBeenCalledTimes(2); // put back on top, so staying stays
    expect(go).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('stays on Stay, with the edits intact and the next Back asking again', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack();
    await click(dialogButton('Stay and keep editing'));
    expect(document.body.textContent).not.toContain(TITLE);
    expect(field('text-en-title').value).toBe('Changed');
    expect(go).not.toHaveBeenCalled();
    await pressBack();
    expect(document.body.textContent).toContain(TITLE);
    expect(inertia).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('leaves on Leave by stepping past the sentinel, without asking twice', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack();
    await click(dialogButton('Leave and discard changes'));
    expect(go).toHaveBeenCalledWith(-2);
    // The step it takes now is Inertia's to handle, not the guard's.
    await pressBack();
    expect(inertia).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain(TITLE);
    await view.unmount();
  });

  it('removes the sentinel once saved, and the swallowed step never reaches Inertia', async () => {
    const view = await open();
    await dirtyForm();
    await submit();
    expect(back).toHaveBeenCalledTimes(1);
    await pressBack(); // the popstate of that removal
    expect(inertia).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain(TITLE);
    await pressBack(); // a real Back afterwards is clean
    expect(inertia).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  it('leaves no entry behind when the page itself closes', async () => {
    const view = await open();
    await dirtyForm();
    await view.unmount();
    expect(back).not.toHaveBeenCalled();
  });

  it('does not visit the fallback when the step back happens (reached by an in-app visit)', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack();
    await click(dialogButton('Leave and discard changes'));
    await pressBack(); // the browser's step, delivered to the guard and to Inertia
    await flush(350);
    expect(inertia).toHaveBeenCalledTimes(1);
    expect(router.visit).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('visits the list when there is nothing to step back to (first page of the tab)', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack();
    await click(dialogButton('Leave and discard changes'));
    expect(go).toHaveBeenCalledWith(-2); // and no popstate follows
    await flush(350);
    expect(router.visit).toHaveBeenCalledWith('/admin/events/list');
    await view.unmount();
  });
});
