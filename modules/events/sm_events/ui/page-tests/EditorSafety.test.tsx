// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { type Call, eventDetail, field, flush, refusal, stubFetch } from './support';
import { act, click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { router } = await import('@inertiajs/react');
const { default: EventEditor } = await import('../../pages/EventEditor');
const { usePreview } = await import('../hooks/usePreview');
const API = '/api/events/events';
const props = {
  event_id: 'e1',
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en', 'de'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};
const PANEL = 'section[aria-label="Someone else saved this event first"]';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.mocked(router.visit).mockClear();
  vi.mocked(router.on).mockClear();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

const submitForm = async () => {
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
};
const patches = (calls: Call[]) => calls.filter((c) => c.method === 'PATCH');

describe('the conflict panel owns the way out', () => {
  async function conflicted(patch: () => unknown) {
    let loads = 0;
    const calls = stubFetch({
      [`GET ${API}/e1`]: () =>
        loads++ === 0 ? eventDetail({ revision: 4 }) : eventDetail({ revision: 5 }),
      [`PATCH ${API}/e1`]: patch,
    });
    const view = await mount(<EventEditor {...props} />);
    await flush();
    await setValue(field('text-en-title'), 'Mine');
    await submitForm();
    return { calls, view };
  }

  it('disables the ordinary Save and says why, and Enter saves nothing', async () => {
    const { calls, view } = await conflicted(() => refusal(409, 'stale'));
    expect(view.find(PANEL)).not.toBeNull();
    const save = view.all('form button').find((b) => b.textContent === 'Save');
    expect(save?.hasAttribute('disabled')).toBe(true);
    expect(view.host.textContent).toContain('Choose Load their version or Save mine over theirs');
    await submitForm();
    expect(patches(calls)).toHaveLength(1);
    await view.unmount();
  });

  it('a successful Save mine closes the panel and enables nothing stale', async () => {
    let n = 0;
    const { calls, view } = await conflicted(() =>
      n++ === 0 ? refusal(409, 'stale') : eventDetail({ revision: 6 }),
    );
    await click(view.button('Save mine over theirs'));
    await flush();
    expect(patches(calls)).toHaveLength(2);
    expect(view.find(PANEL)).toBeNull();
    await view.unmount();
  });

  it('a failed Save mine keeps the panel open', async () => {
    let n = 0;
    const { view } = await conflicted(() =>
      n++ === 0 ? refusal(409, 'stale') : refusal(500, 'boom'),
    );
    await click(view.button('Save mine over theirs'));
    await flush();
    expect(view.find(PANEL)).not.toBeNull();
    await view.unmount();
  });
});

describe('an action in flight never overwrites what was typed meanwhile', () => {
  const draft = (extra = {}) => eventDetail({ revision: 4, status: 'draft', ...extra });
  it('keeps the title typed after clicking Submit and takes the server-owned fields', async () => {
    let release: (value: unknown) => void = () => {};
    stubFetch({
      [`GET ${API}/e1`]: () => draft(),
      [`POST ${API}/e1/submit`]: () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    });
    const view = await mount(<EventEditor {...props} />);
    await flush();
    await click(view.button('Submit for review'));
    await setValue(field('text-en-title'), 'Typed meanwhile');
    release(eventDetail({ revision: 5, status: 'in_review' }));
    await flush();
    expect(field('text-en-title').value).toBe('Typed meanwhile');
    expect(view.host.textContent).toContain('Withdraw from review');
    expect(view.host.textContent).toContain('Your edits made meanwhile are kept');
    // The edit is still unsaved and would be sent against the new revision.
    expect(
      view
        .all('form button')
        .find((b) => b.textContent === 'Save')
        ?.hasAttribute('disabled'),
    ).toBe(false);
    await view.unmount();
  });

  it('adopts the answer when nothing was typed', async () => {
    stubFetch({
      [`GET ${API}/e1`]: () => draft(),
      [`POST ${API}/e1/submit`]: () => eventDetail({ revision: 5, status: 'in_review' }),
    });
    const view = await mount(<EventEditor {...props} />);
    await flush();
    await click(view.button('Submit for review'));
    await flush();
    expect(view.host.textContent).not.toContain('kept');
    expect(view.host.textContent).toContain('Withdraw from review');
    await view.unmount();
  });
});

describe('unsaved changes', () => {
  const handler = () => {
    const call = vi.mocked(router.on).mock.calls.find(([name]) => name === 'before');
    return call?.[1] as unknown as (event: unknown) => void;
  };
  const visit = (only: string[] = []) => ({
    detail: {
      visit: {
        only,
        url: new URL('http://localhost/admin/events/list'),
        method: 'get',
        data: {},
        replace: false,
      },
    },
    preventDefault: vi.fn(),
  });
  const open = async () => {
    stubFetch({ [`GET ${API}/e1`]: () => eventDetail({ revision: 4 }) });
    const view = await mount(<EventEditor {...props} />);
    await flush();
    return view;
  };
  const unload = () => {
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };

  it('is quiet while clean', async () => {
    const view = await open();
    const event = visit();
    handler()(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(unload()).toBe(false);
    await view.unmount();
  });

  it('holds a visit while dirty, asks in the page, and leaves on request', async () => {
    const view = await open();
    await setValue(field('text-en-title'), 'Changed');
    expect(unload()).toBe(true);
    const event = visit();
    await act(async () => handler()(event));
    expect(event.preventDefault).toHaveBeenCalled();
    expect(document.body.textContent).toContain('Leave without saving?');
    expect(router.visit).not.toHaveBeenCalled();
    await click(
      [...document.querySelectorAll('button')].find(
        (b) => b.textContent === 'Stay and keep editing',
      ),
    );
    expect(document.body.textContent).not.toContain('Leave without saving?');
    await act(async () => handler()(visit()));
    await click(
      [...document.querySelectorAll('button')].find(
        (b) => b.textContent === 'Leave and discard changes',
      ),
    );
    expect(router.visit).toHaveBeenCalledTimes(1);
    expect(String(vi.mocked(router.visit).mock.calls[0]?.[0])).toBe(
      'http://localhost/admin/events/list',
    );
    await view.unmount();
  });

  it('lets a partial reload through and is quiet right after a save', async () => {
    const view = await open();
    await setValue(field('text-en-title'), 'Changed');
    const partial = visit(['items']);
    handler()(partial);
    expect(partial.preventDefault).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
    stubFetch({ [`PATCH ${API}/e1`]: () => eventDetail({ revision: 5 }) });
    await submitForm();
    const after = visit();
    handler()(after);
    expect(after.preventDefault).not.toHaveBeenCalled();
    expect(unload()).toBe(false);
    await view.unmount();
  });
});

function Probe({ rrule }: { rrule: string }) {
  const p = usePreview({
    times: {
      all_day: false,
      timezone: 'Europe/Vienna',
      start: '2026-03-02T10:00',
      end: '2026-03-02T11:00',
    },
    rrule,
    eventId: null,
    calendarId: 'c1',
  });
  return <div>{p.occurrences.map((o) => o.start_local).join(',')}</div>;
}

describe('the recurrence preview', () => {
  beforeEach(() => vi.useRealTimers());
  it('never shows an old rule after a newer edit', async () => {
    let release: (value: unknown) => void = () => {};
    stubFetch({
      'POST /api/events/recurrence/preview': (call: Call) =>
        (call.body as { rrule: string }).rrule === 'FREQ=DAILY'
          ? new Promise((resolve) => {
              release = resolve;
            })
          : {
              occurrences: [{ start: 'z', end: 'z', start_local: 'new', end_local: 'new' }],
              recurrence_until: null,
              orphaned: [],
            },
    });
    const view = await mount(<Probe rrule="FREQ=DAILY" />);
    await flush(500); // the old rule's request is now in flight
    await view.render(<Probe rrule="FREQ=WEEKLY;BYDAY=MO" />);
    release({
      occurrences: [{ start: 'a', end: 'a', start_local: 'old', end_local: 'old' }],
      recurrence_until: null,
      orphaned: [],
    });
    await flush(10);
    expect(view.host.textContent).not.toContain('old');
    await flush(500);
    expect(view.host.textContent).toBe('new');
    await view.unmount();
  });
});
