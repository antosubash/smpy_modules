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

/** The browser as Chrome really behaves, which happy-dom does not model:
 *
 *  - Inertia's `popstate` listener is added to `window` when the app boots,
 *    before any page mounts, and Chrome runs a window's listeners in the order
 *    they were added, capture or not (happy-dom runs capture ones first, which
 *    is why a capture listener that stopped the event looked enough here and
 *    was not in Chrome). Once Inertia sees the event it restores the other
 *    page, so a guard that waits for `popstate` is always too late.
 *  - A step through the history first fires the Navigation API's `navigate`,
 *    cancellable only while the user has interacted since the last cancel. A
 *    cancelled step moves nothing and fires no `popstate`.
 *  - happy-dom has no `navigation` at all; this fake stands in for it. */
let inertia: ReturnType<typeof vi.fn<(e: PopStateEvent) => void>>;
let nav: (EventTarget & { traverseTo: ReturnType<typeof vi.fn> }) | null;
let push: ReturnType<typeof vi.spyOn>;
let back: ReturnType<typeof vi.spyOn>;

function fakeNavigation() {
  const target = new EventTarget() as EventTarget & { traverseTo: ReturnType<typeof vi.fn> };
  target.traverseTo = vi.fn((key: string) => {
    // A step the page asked for is script-initiated, so always cancellable.
    const went = step({ key, cancelable: true });
    return { finished: went ? Promise.resolve() : Promise.reject(new Error('AbortError')) };
  });
  return target;
}

/** One step back as Chrome delivers it; answers whether the history moved. */
function step({ key = 'list', cancelable = true, sameDocument = true } = {}): boolean {
  if (nav) {
    const e = Object.assign(new Event('navigate', { cancelable }), {
      navigationType: 'traverse',
      destination: { key, sameDocument },
    });
    nav.dispatchEvent(e);
    if (e.defaultPrevented) return false;
  }
  if (!sameDocument) return true;
  const pop = new PopStateEvent('popstate', { state: { page: { url: '/admin/events/list' } } });
  inertia(pop); // first, as registered at boot
  window.dispatchEvent(pop);
  return true;
}
const pressBack = (options?: Parameters<typeof step>[0]) => act(async () => void step(options));

beforeEach(() => {
  inertia = vi.fn<(e: PopStateEvent) => void>();
  nav = fakeNavigation();
  vi.stubGlobal('navigation', nav);
  push = vi.spyOn(window.history, 'pushState');
  back = vi.spyOn(window.history, 'back').mockImplementation(() => {});
  vi.spyOn(window.history, 'go').mockImplementation(() => {});
});
afterEach(() => {
  vi.mocked(router.visit).mockClear();
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
  return view;
}
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
  it('is not held while the form is clean', async () => {
    const view = await open();
    await pressBack();
    expect(inertia).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain(TITLE);
    await view.unmount();
  });

  it('is held before the history moves, so Inertia never restores the other page', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack();
    expect(inertia).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(TITLE);
    expect(field('text-en-title').value).toBe('Changed');
    // No entry of its own: the history is the user's, at every point.
    expect(push).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('stays on Stay, with the edits intact and the next Back asking again', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack();
    await click(dialogButton('Stay and keep editing'));
    expect(document.body.textContent).not.toContain(TITLE);
    expect(field('text-en-title').value).toBe('Changed');
    await pressBack();
    expect(document.body.textContent).toContain(TITLE);
    expect(inertia).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('takes the held step on Leave, without asking twice', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack({ key: 'list-entry' });
    await act(async () => void dialogButton('Leave and discard changes')?.click());
    await flush();
    expect(nav?.traverseTo).toHaveBeenCalledWith('list-entry');
    expect(inertia).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain(TITLE);
    expect(router.visit).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('visits the list when the held step cannot be taken any more', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack();
    nav?.traverseTo.mockReturnValueOnce({ finished: Promise.reject(new Error('gone')) });
    await click(dialogButton('Leave and discard changes'));
    await flush();
    expect(router.visit).toHaveBeenCalledWith('/admin/events/list');
    await view.unmount();
  });

  it('leaves at once after a save: nothing to clean up, nothing to swallow', async () => {
    const view = await open();
    await dirtyForm();
    await submit();
    expect(back).not.toHaveBeenCalled();
    await pressBack();
    expect(inertia).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain(TITLE);
    await view.unmount();
  });

  it('lets a step through that the browser will not let it cancel, rather than trap the page', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack({ cancelable: false });
    expect(inertia).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain(TITLE);
    await view.unmount();
  });

  it('leaves a step to another document to beforeunload', async () => {
    const view = await open();
    await dirtyForm();
    await pressBack({ sameDocument: false });
    expect(document.body.textContent).not.toContain(TITLE);
    const unload = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);
    await view.unmount();
  });

  it('adds no history entry and holds nothing without the Navigation API', async () => {
    nav = null;
    vi.stubGlobal('navigation', undefined);
    const view = await open();
    await dirtyForm();
    await pressBack();
    expect(push).not.toHaveBeenCalled();
    expect(inertia).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).not.toContain(TITLE);
    await view.unmount();
  });
});
