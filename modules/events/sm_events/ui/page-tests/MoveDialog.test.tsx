// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { occurrence } from './calendar-support';
import {
  api,
  EVENT,
  Harness,
  installHarness,
  instance,
  invalidate,
  mounted,
  oneOff,
  weekly,
} from './calendar-writes-support';
import { button, eventDetail, field, flush, refusal, stubFetch, submit } from './support';
import { click, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { MoveDialog } = await import('../calendar/console/MoveDialog');
const radio = (label: string) =>
  [...document.querySelectorAll<HTMLInputElement>('input[type="radio"]')].find((r) =>
    r.closest('label')?.textContent?.includes(label),
  );

/** The dialog over the real write flow, as the console wires it. */
function Wired({
  o,
  returnFocus,
}: {
  o: ReturnType<typeof occurrence>;
  returnFocus?: HTMLElement;
}) {
  return (
    <>
      <Harness />
      <MoveDialog
        occurrence={o}
        returnFocus={returnFocus}
        onSubmit={(change, scope) =>
          api.current?.submit(change, scope) ?? Promise.resolve({ ok: false } as never)
        }
        onClose={onClose}
      />
    </>
  );
}
const onClose = vi.fn();

installHarness();
beforeEach(() => onClose.mockClear());

async function open(o = occurrence(), returnFocus?: HTMLElement) {
  await mounted.view?.render(<Wired o={o} returnFocus={returnFocus} />);
  await flush();
}

describe('MoveDialog', () => {
  it('prefills the event-local times and names the zone', async () => {
    await open();
    expect(field('move-start').value).toBe('2026-03-23T10:00');
    expect(field('move-end').value).toBe('2026-03-23T11:00');
    expect(document.body.textContent).toContain('Europe/Vienna');
    expect(radio('Only this occurrence')).toBeUndefined();
  });

  it('refuses an end before the start locally, at the end field', async () => {
    const calls = stubFetch({});
    await open();
    await setValue(field('move-end'), '2026-03-23T09:00');
    await submit();
    expect(calls).toHaveLength(0);
    const end = field('move-end');
    expect(end.getAttribute('aria-invalid')).toBe('true');
    const message = document.getElementById(end.getAttribute('aria-describedby') ?? '');
    expect(message?.textContent).toBe('The end must be after the start.');
    expect(document.activeElement).toBe(end);
  });

  it('refuses a time the clocks skip, at the start field', async () => {
    const calls = stubFetch({});
    await open();
    await setValue(field('move-start'), '2026-03-29T02:30');
    await setValue(field('move-end'), '2026-03-29T04:00');
    await submit();
    expect(calls).toHaveLength(0);
    expect(field('move-start').getAttribute('aria-invalid')).toBe('true');
  });

  it('sends the same request as a drag', async () => {
    const calls = stubFetch({ [`GET ${EVENT}`]: oneOff(), [`PATCH ${EVENT}`]: oneOff() });
    await open();
    await setValue(field('move-start'), '2026-03-30T11:00');
    await setValue(field('move-end'), '2026-03-30T12:00');
    await submit();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      expected_revision: 7,
      times: {
        all_day: false,
        timezone: 'Europe/Vienna',
        start: '2026-03-30T11:00',
        end: '2026-03-30T12:00',
      },
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('changes only the length when only the end moves', async () => {
    const calls = stubFetch({ [`GET ${EVENT}`]: oneOff(), [`PATCH ${EVENT}`]: oneOff() });
    await open();
    await setValue(field('move-end'), '2026-03-23T12:30');
    await submit();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
      times: { start: '2026-03-23T10:00', end: '2026-03-23T12:30' },
    });
  });

  it('closes without a request when nothing changed', async () => {
    const calls = stubFetch({});
    await open();
    await submit();
    expect(calls).toHaveLength(0);
    expect(onClose).toHaveBeenCalled();
  });

  it('offers this one or all for a series, "this one" first, and all patches the master', async () => {
    const calls = stubFetch({ [`GET ${EVENT}`]: weekly(), [`PATCH ${EVENT}`]: weekly() });
    await open(instance());
    expect(radio('Only this occurrence')?.checked).toBe(true);
    await click(radio('All occurrences'));
    await setValue(field('move-start'), '2026-03-30T11:00');
    await setValue(field('move-end'), '2026-03-30T12:00');
    await submit();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
      times: { start: '2026-03-09T11:00', end: '2026-03-09T12:00' },
    });
    // The dialog chose the scope: no second prompt.
    expect(document.body.textContent).not.toContain('Change a repeating event');
  });

  it('"only this occurrence" posts an override', async () => {
    const calls = stubFetch({
      [`GET ${EVENT}`]: weekly(),
      [`POST ${EVENT}/overrides`]: { id: 1, event_revision: 8 },
    });
    await open(instance());
    await setValue(field('move-start'), '2026-03-30T11:00');
    await setValue(field('move-end'), '2026-03-30T12:00');
    await submit();
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
      kind: 'moved',
      original_start: '2026-03-23T09:00:00Z',
      start: '2026-03-30T11:00',
    });
  });

  it('shows dates only for an all-day occurrence and sends them as a drag would', async () => {
    const allDay = occurrence({
      all_day: true,
      start: '2026-07-31T22:00:00Z',
      end: '2026-08-03T22:00:00Z',
      start_date: '2026-08-01',
      end_date: '2026-08-04',
    });
    const calls = stubFetch({
      [`GET ${EVENT}`]: eventDetail({
        id: 'e1',
        revision: 7,
        all_day: true,
        starts_at: '2026-07-31T22:00:00Z',
        ends_at: '2026-08-03T22:00:00Z',
        start_local: '2026-08-01',
        end_local: '2026-08-03',
      }),
      [`PATCH ${EVENT}`]: oneOff(),
    });
    await open(allDay);
    expect(field('move-start').type).toBe('date');
    expect(field('move-end').value).toBe('2026-08-03');
    await setValue(field('move-start'), '2026-08-03');
    await setValue(field('move-end'), '2026-08-05');
    await submit();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({
      times: { all_day: true, start: '2026-08-03', end: '2026-08-05' },
    });
  });

  it('keeps the dialog open with the message when the write is refused', async () => {
    stubFetch({ [`GET ${EVENT}`]: oneOff(), [`PATCH ${EVENT}`]: refusal(409, 'stale') });
    await open();
    await setValue(field('move-start'), '2026-03-30T11:00');
    await setValue(field('move-end'), '2026-03-30T12:00');
    await submit();
    expect(onClose).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      'changed since it was loaded',
    );
    expect(invalidate).toHaveBeenCalled();
  });

  it('puts a server refusal that names an end at that field', async () => {
    stubFetch({
      [`GET ${EVENT}`]: oneOff(),
      [`PATCH ${EVENT}`]: Response.json(
        { detail: 'too long', code: 'duration_too_long', field: 'times.end' },
        { status: 422 },
      ),
    });
    await open();
    await setValue(field('move-end'), '2028-03-23T12:30');
    await submit();
    expect(field('move-end').getAttribute('aria-invalid')).toBe('true');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('focuses the first field on open and gives focus back to the event on close', async () => {
    const element = document.createElement('button');
    document.body.appendChild(element);
    await open(occurrence(), element);
    expect(document.activeElement).toBe(field('move-start'));
    await click(button('Cancel'));
    expect(onClose).toHaveBeenCalled();
    // The shell closes the dialog; Radix then returns focus to the event's element.
    await mounted.view?.render(<Harness />);
    await flush();
    expect(document.activeElement).toBe(element);
  });

  it('hands focus back even when the shell has already forgotten the element', async () => {
    const element = document.createElement('button');
    document.body.appendChild(element);
    const restoreFocus = vi.fn();
    const dialog = (o: ReturnType<typeof occurrence> | null, el?: HTMLElement) => (
      <MoveDialog
        occurrence={o}
        returnFocus={el}
        restoreFocus={restoreFocus}
        onSubmit={() => Promise.resolve({ ok: true })}
        onClose={onClose}
      />
    );
    const o = occurrence();
    await mounted.view?.render(dialog(o, element));
    await flush();
    await mounted.view?.render(dialog(null, undefined));
    await flush();
    expect(restoreFocus).toHaveBeenCalledWith(o, element);
  });
});
