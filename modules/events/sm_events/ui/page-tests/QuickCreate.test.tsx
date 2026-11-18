// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CalendarInfo, CreateSlot } from '../calendar/types';
import { calendarInfo } from './calendar-support';
import { button, eventDetail, field, flush, stubFetch, submit, unprocessable } from './support';
import { act, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { QuickCreateDialog } = await import('../calendar/console/QuickCreateDialog');

const EVENTS = '/api/events/events';
const VIENNA = calendarInfo({ id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' });
const NEW_YORK = calendarInfo({ id: 'c2', name: 'Board', default_timezone: 'America/New_York' });
const READ_ONLY = calendarInfo({ id: 'c3', name: 'Archive', can_write_events: false });
const TIMED: CreateSlot = {
  allDay: false,
  start: '2026-07-01T08:00:00Z',
  end: '2026-07-01T09:00:00Z',
};

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

async function open(slot: CreateSlot, calendars: CalendarInfo[] = [VIENNA], preferred = 'c1') {
  const onCreated = vi.fn();
  const onClose = vi.fn();
  const view = await mount(
    <QuickCreateDialog
      slot={slot}
      calendars={calendars}
      preferred={preferred}
      defaultLocale="en"
      editorUrl="/admin/events/edit"
      onCreated={onCreated}
      onClose={onClose}
    />,
  );
  await flush();
  return { view, onCreated, onClose };
}
const select = () => field('quick-calendar') as HTMLSelectElement;

describe('without a writable calendar', () => {
  it('renders no dialog and no link without a calendar id', async () => {
    const { view } = await open(TIMED, [{ ...VIENNA, can_write_events: false }]);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.body.innerHTML).not.toContain('edit/new?calendar=&');
    await view.unmount();
  });
});

describe('the slot', () => {
  it("prefills local times in the calendar's zone and names it", async () => {
    const { view } = await open(TIMED);
    expect(field('quick-start').value).toBe('2026-07-01T10:00');
    expect(field('quick-end').value).toBe('2026-07-01T11:00');
    expect(document.body.textContent).toContain('Europe/Vienna');
    await view.unmount();
  });

  it('re-expresses the same instants when the calendar changes', async () => {
    const { view } = await open(TIMED, [VIENNA, NEW_YORK]);
    await setValue(select(), 'c2');
    expect(field('quick-start').value).toBe('2026-07-01T04:00');
    expect(field('quick-end').value).toBe('2026-07-01T05:00');
    expect(document.body.textContent).toContain('America/New_York');
    await view.unmount();
  });

  it('shows an all-day span with an inclusive last day', async () => {
    const { view } = await open({ allDay: true, start: '2026-08-01', end: '2026-08-04' });
    expect(field('quick-start').type).toBe('date');
    expect(field('quick-start').value).toBe('2026-08-01');
    expect(field('quick-end').value).toBe('2026-08-03');
    await view.unmount();
  });

  it('offers only the calendars the viewer can write to', async () => {
    const { view } = await open(TIMED, [VIENNA, READ_ONLY, NEW_YORK]);
    expect([...select().options].map((o) => o.textContent)).toEqual(['Team', 'Board']);
    await view.unmount();
  });

  it('starts on the preferred calendar', async () => {
    const { view } = await open(TIMED, [VIENNA, NEW_YORK], 'c2');
    expect(select().value).toBe('c2');
    expect(field('quick-start').value).toBe('2026-07-01T04:00');
    await view.unmount();
  });
});

describe('create', () => {
  it('posts a draft with the default-language title and the local times', async () => {
    const calls = stubFetch({ [`POST ${EVENTS}`]: () => eventDetail({ id: 'new1' }) });
    const { view, onCreated } = await open(TIMED);
    await setValue(field('quick-title'), 'Concert');
    await submit();
    const body = calls.find((c) => c.method === 'POST')?.body;
    expect(body).toMatchObject({
      calendar_id: 'c1',
      times: {
        all_day: false,
        timezone: 'Europe/Vienna',
        start: '2026-07-01T10:00',
        end: '2026-07-01T11:00',
      },
      texts: { en: { title: 'Concert' } },
    });
    expect(onCreated).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  it('posts all-day dates with the inclusive end', async () => {
    const calls = stubFetch({ [`POST ${EVENTS}`]: () => eventDetail({ id: 'new1' }) });
    const { view } = await open({ allDay: true, start: '2026-08-01', end: '2026-08-04' });
    await setValue(field('quick-title'), 'Retreat');
    await submit();
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
      times: { all_day: true, start: '2026-08-01', end: '2026-08-03' },
    });
    await view.unmount();
  });

  it('requires a title and sends nothing without one', async () => {
    const calls = stubFetch({});
    const { view } = await open(TIMED);
    await submit();
    expect(calls).toHaveLength(0);
    const title = field('quick-title');
    expect(title.getAttribute('aria-invalid')).toBe('true');
    const message = document.getElementById(title.getAttribute('aria-describedby') ?? '');
    expect(message?.textContent).toBe('This field is required.');
    expect(document.activeElement).toBe(title);
    await view.unmount();
  });

  it('refuses an end before the start at the end field', async () => {
    const calls = stubFetch({});
    const { view } = await open(TIMED);
    await setValue(field('quick-title'), 'Concert');
    await setValue(field('quick-end'), '2026-07-01T09:00');
    await submit();
    expect(calls).toHaveLength(0);
    expect(field('quick-end').getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(field('quick-end'));
    await view.unmount();
  });

  it('refuses a time the clocks skip, at the start field', async () => {
    const calls = stubFetch({});
    const { view } = await open(TIMED);
    await setValue(field('quick-title'), 'Concert');
    await setValue(field('quick-start'), '2026-03-29T02:30');
    await setValue(field('quick-end'), '2026-03-29T04:00');
    await submit();
    expect(calls).toHaveLength(0);
    expect(field('quick-start').getAttribute('aria-invalid')).toBe('true');
    await view.unmount();
  });

  it('puts a server field error at its field and keeps what was typed', async () => {
    stubFetch({ [`POST ${EVENTS}`]: () => unprocessable(['texts', 'en', 'title']) });
    const { view, onCreated } = await open(TIMED);
    await setValue(field('quick-title'), 'Concert');
    await submit();
    expect(field('quick-title').getAttribute('aria-invalid')).toBe('true');
    expect(field('quick-title').value).toBe('Concert');
    expect(onCreated).not.toHaveBeenCalled();
    await view.unmount();
  });
});

describe('More options', () => {
  it('links to the editor with the slot, the calendar and the title', async () => {
    const { view } = await open(TIMED);
    await setValue(field('quick-title'), 'Team sync & lunch');
    const link = [...document.querySelectorAll('a')].find((a) =>
      a.textContent?.includes('More options'),
    );
    expect(link?.getAttribute('href')).toBe(
      '/admin/events/edit/new?calendar=c1&all_day=0&start=2026-07-01T10%3A00&end=2026-07-01T11%3A00&title=Team%20sync%20%26%20lunch',
    );
    await view.unmount();
  });

  it('carries an all-day span with its inclusive last day, and no empty title', async () => {
    const { view } = await open({ allDay: true, start: '2026-08-01', end: '2026-08-04' });
    const link = [...document.querySelectorAll('a')].find((a) =>
      a.textContent?.includes('More options'),
    );
    expect(link?.getAttribute('href')).toBe(
      '/admin/events/edit/new?calendar=c1&all_day=1&start=2026-08-01&end=2026-08-03',
    );
    await view.unmount();
  });
});

describe('closing', () => {
  it('cancel closes without a request', async () => {
    const calls = stubFetch({});
    const { view, onClose } = await open(TIMED);
    await act(async () => button('Cancel').click());
    expect(onClose).toHaveBeenCalled();
    expect(calls).toHaveLength(0);
    await view.unmount();
  });
});
