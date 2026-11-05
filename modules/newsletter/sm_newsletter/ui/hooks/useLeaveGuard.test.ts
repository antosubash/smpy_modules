// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../locales/en.json';
import { useLeaveGuard } from './useLeaveGuard';

type Before = (event: {
  detail: { visit: { only: string[] } };
  preventDefault: () => void;
}) => void;
const listeners = vi.hoisted(() => [] as Before[]);
vi.mock('@inertiajs/react', () => ({
  router: {
    on: (_name: string, cb: Before) => {
      listeners.push(cb);
      return () => listeners.splice(listeners.indexOf(cb), 1);
    },
  },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let state = { dirty: false, held: false };
function Harness() {
  useLeaveGuard(state);
  return null;
}

/** An Inertia visit: whether the guard stopped it. */
function visit(only: string[] = []): boolean {
  let stopped = false;
  for (const cb of listeners)
    cb({ detail: { visit: { only } }, preventDefault: () => (stopped = true) });
  return stopped;
}

describe('useLeaveGuard', () => {
  let root: ReturnType<typeof createRoot>;
  let confirm: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    confirm = vi.fn(() => false);
    vi.stubGlobal('confirm', confirm);
  });
  afterEach(() => {
    act(() => root.unmount());
    vi.unstubAllGlobals();
    expect(listeners).toHaveLength(0);
  });

  async function mount(next: typeof state) {
    state = next;
    root = createRoot(document.createElement('div'));
    await act(async () => root.render(createElement(Harness)));
  }

  it('lets an in-app visit through while the edits can still be flushed', async () => {
    await mount({ dirty: true, held: false });
    expect(visit()).toBe(false);
    expect(confirm).not.toHaveBeenCalled();
  });

  it('asks before an in-app visit drops an unfinished block', async () => {
    await mount({ dirty: true, held: true });
    expect(visit()).toBe(true);
    expect(confirm).toHaveBeenCalledWith(en.editor.leave_held);
    confirm.mockReturnValue(true);
    expect(visit()).toBe(false);
    // A partial reload stays on the page.
    confirm.mockClear();
    expect(visit(['campaign'])).toBe(false);
    expect(confirm).not.toHaveBeenCalled();
  });

  it('asks before the tab closes only while something is unsaved', async () => {
    await mount({ dirty: true, held: false });
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    act(() => root.unmount());
    await mount({ dirty: false, held: false });
    const clean = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
  });
});
