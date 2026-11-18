// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import {
  EDITOR,
  EVENT,
  finish,
  installHarness,
  instance,
  invalidate,
  methods,
  move,
  oneOff,
  PREVIEW,
  start,
  weekly,
} from './calendar-writes-support';
import { button, flush, refusal, stubFetch } from './support';
import { click, mount } from './test-dom';

vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { toast } = await import('sonner');
installHarness();

describe('refusals', () => {
  it('a client-side stale stops before any write and refreshes', async () => {
    const calls = stubFetch({
      [`GET ${EVENT}`]: { ...oneOff(), starts_at: '2026-03-24T09:00:00Z' },
    });
    expect(await finish(start(move()))).toBe(false);
    expect(methods(calls)).toEqual(['GET']);
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining('changed since it was loaded'),
    );
  });

  it('a 409 stale reverts and refreshes', async () => {
    stubFetch({ [`GET ${EVENT}`]: oneOff(), [`PATCH ${EVENT}`]: refusal(409, 'stale') });
    expect(await finish(start(move()))).toBe(false);
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining('changed since it was loaded'),
    );
  });

  it('a 409 overrides_orphaned lists them, and confirming resends with the flag', async () => {
    const orphan = {
      id: 5,
      original_start: '2026-04-06T08:00:00Z',
      kind: 'cancelled',
      starts_at: null,
      ends_at: null,
      start_local: null,
      end_local: null,
      note: null,
    };
    let patches = 0;
    const calls = stubFetch({
      [`GET ${EVENT}`]: weekly(),
      [`PATCH ${EVENT}`]: () => (++patches === 1 ? refusal(409, 'overrides_orphaned') : weekly()),
      [`POST ${PREVIEW}`]: { occurrences: [], recurrence_until: null, orphaned: [orphan] },
    });
    const done = start(move(instance()));
    await flush();
    await click(button('All occurrences'));
    await flush();
    expect(document.body.textContent).toContain('Changed occurrences will be removed');
    await click(button('Save and remove them'));
    expect(await finish(done)).toBe(true);
    expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
      expect.not.objectContaining({ drop_orphaned_overrides: true }),
      expect.objectContaining({ drop_orphaned_overrides: true }),
    ]);
    expect(calls.find((c) => c.url === PREVIEW)?.body).toMatchObject({
      event_id: 'e1',
      rrule: 'FREQ=WEEKLY;BYDAY=MO',
    });
  });

  it('cancelling the orphans confirm reverts and writes nothing more', async () => {
    const orphan = {
      id: 5,
      original_start: '2026-04-06T08:00:00Z',
      kind: 'skipped',
      starts_at: null,
      ends_at: null,
      start_local: null,
      end_local: null,
      note: null,
    };
    const calls = stubFetch({
      [`GET ${EVENT}`]: weekly(),
      [`PATCH ${EVENT}`]: refusal(409, 'overrides_orphaned'),
      [`POST ${PREVIEW}`]: { occurrences: [], recurrence_until: null, orphaned: [orphan] },
    });
    const done = start(move(instance()));
    await flush();
    await click(button('All occurrences'));
    await flush();
    await click(button('Cancel'));
    expect(await finish(done)).toBe(false);
    expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1);
    expect(toast.error).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('a 403 publish_required reverts with the reason', async () => {
    stubFetch({ [`GET ${EVENT}`]: oneOff(), [`PATCH ${EVENT}`]: refusal(403, 'publish_required') });
    expect(await finish(start(move()))).toBe(false);
    expect(toast.error).toHaveBeenCalledWith(
      'Only a publisher can change a published or scheduled event.',
    );
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it('a 404 says the event is gone and refreshes', async () => {
    stubFetch({ [`GET ${EVENT}`]: refusal(404, 'not_found') });
    expect(await finish(start(move()))).toBe(false);
    expect(toast.error).toHaveBeenCalledWith('This event no longer exists.');
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it('a 422 start_not_in_rule offers the editor', async () => {
    stubFetch({
      [`GET ${EVENT}`]: weekly(),
      [`PATCH ${EVENT}`]: refusal(422, 'start_not_in_rule'),
    });
    const done = start(move(instance()));
    await flush();
    await click(button('All occurrences'));
    expect(await finish(done)).toBe(false);
    const shown = vi.mocked(toast.error).mock.calls[0]?.[0];
    const probe = await mount(<div>{shown as never}</div>);
    expect(probe.host.textContent).toContain('changes its rule');
    expect(probe.find('a')?.getAttribute('href')).toBe(`${EDITOR}/e1`);
    await probe.unmount();
  });

  it('a change onto the repeated hour is refused without a write', async () => {
    const calls = stubFetch({
      [`GET ${EVENT}`]: oneOff(),
    });
    const change = { ...move(), start: '2026-10-25T01:30:00Z', end: '2026-10-25T02:30:00Z' };
    expect(await finish(start(change))).toBe(false);
    expect(methods(calls)).toEqual(['GET']);
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining('happens twice in Europe/Vienna'),
    );
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it('a network failure reverts with the offline text', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    expect(await finish(start(move()))).toBe(false);
    expect(toast.error).toHaveBeenCalledWith('Could not reach the server. Check your connection.');
    expect(invalidate).toHaveBeenCalledTimes(1);
  });
});
