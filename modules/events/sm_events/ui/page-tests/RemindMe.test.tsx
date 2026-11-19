// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { resetReminderStatus } from '../utils/api-reminders';
import { flush, refusal, stubFetch } from './support';
import { click, mount, press } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { RemindMe } = await import('../reminders/RemindMe');

const STATUS = '/api/events/reminders/status';
const FOLLOW = '/api/events/events/e1/follow';
const LEADS = [15, 60, 1440, 10080];
const available = { available: true, leads: LEADS };
const follow = (over = {}) => ({
  leads: [],
  defaults: [60],
  next_due: {},
  deliverable: true,
  code: null,
  ...over,
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetReminderStatus();
  document.body.innerHTML = '';
});

const control = () => document.querySelector<HTMLButtonElement>('[data-testid="remind-me"] button');
const box = (lead: number) =>
  [...document.querySelectorAll<HTMLElement>('[role="checkbox"]')].find((b) =>
    b.id.endsWith(`-${lead}`),
  );
const text = (re: RegExp) =>
  [...document.querySelectorAll('button')].find((b) => re.test(b.textContent ?? ''));

async function open(routes: Record<string, unknown>) {
  const calls = stubFetch({ [`GET ${STATUS}`]: available, ...routes });
  const view = await mount(<RemindMe eventId="e1" eventZone="Europe/Vienna" />);
  await flush();
  return { calls, view };
}

describe('RemindMe', () => {
  it('shows nothing while loading and nothing when the event is gone for this user', async () => {
    const { view } = await open({ [`GET ${FOLLOW}`]: () => refusal(404, 'not_found') });
    expect(view.host.querySelector('[data-testid="remind-me"]')).toBeNull();
    expect(view.host.textContent).toBe('');
    await view.unmount();
  });

  it('says why in words when reminders cannot be delivered, never a dead control', async () => {
    const { view } = await open({
      [`GET ${STATUS}`]: { available: false, reason: 'console_mail', leads: LEADS },
    });
    expect(control()).toBeNull();
    const note = view.host.querySelector('[data-testid="remind-unavailable"]');
    expect(note?.textContent).toContain('not available');
    expect(note?.textContent).toContain('console');
    await view.unmount();
  });

  it('keeps the reason from everyone but managers out of it', async () => {
    const { view } = await open({ [`GET ${STATUS}`]: { available: false, leads: LEADS } });
    expect(view.host.textContent).toContain('not available');
    expect(view.host.textContent).not.toContain('console');
    await view.unmount();
  });

  it('preselects the calendar defaults when not following, and saves the chosen set', async () => {
    const { calls, view } = await open({
      [`GET ${FOLLOW}`]: follow({ defaults: [60] }),
      [`PUT ${FOLLOW}`]: (call: { body: unknown }) =>
        follow({
          leads: (call.body as { leads: number[] }).leads,
          next_due: { '60': '2026-07-01T09:00:00Z', '1440': null },
        }),
    });
    expect(control()?.textContent).toBe('Remind me');
    await click(control());
    expect(box(60)?.getAttribute('aria-checked')).toBe('true');
    expect(box(15)?.getAttribute('aria-checked')).toBe('false');
    await click(box(1440));
    await click(text(/^Save$/));
    await flush();
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ leads: [60, 1440] });
    expect(control()?.textContent).toBe('Reminding: 1 h, 1 day');
    await view.unmount();
  });

  it('shows the next due time in the browser zone and names the event zone', async () => {
    const { view } = await open({
      [`GET ${FOLLOW}`]: follow({
        leads: [60, 1440],
        next_due: { '60': '2026-07-01T09:00:00Z', '1440': null },
      }),
    });
    await click(control());
    const text = view.host.textContent ?? '';
    expect(text).toContain('1 hour before: next reminder');
    expect(text).toContain('1 day before: too late for the next occurrence');
    expect(text).toContain('Europe/Vienna');
    await view.unmount();
  });

  it('stopping sends DELETE and goes back to Remind me', async () => {
    const { calls, view } = await open({
      [`GET ${FOLLOW}`]: follow({ leads: [60] }),
      [`DELETE ${FOLLOW}`]: null,
    });
    await click(control());
    await click(text(/Stop reminding/));
    await flush();
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
    expect(control()?.textContent).toBe('Remind me');
    await view.unmount();
  });

  it('puts the optimistic change back and says why when the server refuses', async () => {
    const { view } = await open({
      [`GET ${FOLLOW}`]: follow(),
      [`PUT ${FOLLOW}`]: () => refusal(409, 'follow_limit'),
    });
    await click(control());
    await click(text(/^Save$/));
    await flush();
    expect(control()?.textContent).toBe('Remind me');
    const text = document.querySelector('[role="alert"]')?.textContent ?? '';
    expect(text).toContain('most events');
    expect(text.match(/first/g)).toHaveLength(1); // one sentence, not three
    await view.unmount();
  });

  it('tells a user the worker could not verify, and keeps the follow', async () => {
    const { view } = await open({
      [`GET ${FOLLOW}`]: follow({ leads: [60], deliverable: false, code: 'reminders_no_access' }),
    });
    expect(view.host.textContent).toContain(
      'cannot be sent for this event with your current access',
    );
    expect(control()?.textContent).toContain('Reminding');
    await view.unmount();
  });

  it('is a keyboard control: focus goes in on open, Escape closes and returns to the button', async () => {
    const { view } = await open({ [`GET ${FOLLOW}`]: follow() });
    const toggle = control();
    expect(toggle?.getAttribute('aria-expanded')).toBe('false');
    await click(toggle);
    expect(toggle?.getAttribute('aria-expanded')).toBe('true');
    expect(toggle?.getAttribute('aria-controls')).toBe(
      document.querySelector('[role="group"]')?.id,
    );
    expect(document.activeElement?.getAttribute('role')).toBe('checkbox');
    await press(document.activeElement, { key: 'Escape' });
    expect(document.querySelector('[role="group"]')).toBeNull();
    expect(document.activeElement).toBe(toggle);
    await view.unmount();
  });

  it('asks for the status once however many controls there are', async () => {
    const calls = stubFetch({
      [`GET ${STATUS}`]: available,
      [`GET ${FOLLOW}`]: follow(),
      'GET /api/events/events/e2/follow': follow(),
    });
    const a = await mount(<RemindMe eventId="e1" eventZone="UTC" />);
    const b = await mount(<RemindMe eventId="e2" eventZone="UTC" />);
    await flush();
    expect(calls.filter((c) => c.url === STATUS)).toHaveLength(1);
    await a.unmount();
    await b.unmount();
  });
});

describe('RemindMe cap message', () => {
  it('links the cap message to the list where every follow can be removed', async () => {
    const { view } = await open({
      [`GET ${FOLLOW}`]: follow(),
      [`PUT ${FOLLOW}`]: () => refusal(409, 'follow_limit'),
    });
    await click(control());
    await click(text(/^Save$/));
    await flush();
    const link = [...document.querySelectorAll('a')].find((a) =>
      /your reminders/i.test(a.textContent ?? ''),
    );
    expect(link?.getAttribute('href')).toBe('/admin/events/reminders');
    await view.unmount();
  });

  it('offers no list link for another refusal', async () => {
    const { view } = await open({
      [`GET ${FOLLOW}`]: follow(),
      [`PUT ${FOLLOW}`]: () => refusal(422, 'invalid_lead'),
    });
    await click(control());
    await click(text(/^Save$/));
    await flush();
    expect(document.querySelector('[role="alert"]')).not.toBeNull();
    expect(document.querySelector('a[href="/admin/events/reminders"]')).toBeNull();
    await view.unmount();
  });
});

describe('RemindMe pins', () => {
  it('offers only the lead times the server allows', async () => {
    const { view } = await open({
      [`GET ${STATUS}`]: { available: true, leads: [60, 1440] },
      [`GET ${FOLLOW}`]: follow(),
    });
    await click(control());
    const ids = [...document.querySelectorAll<HTMLElement>('[role="checkbox"]')].map((b) =>
      b.id.replace(/^.*-/, ''),
    );
    expect(ids).toEqual(['60', '1440']);
    await view.unmount();
  });

  it('says once that no mail will come, following or not', async () => {
    const noAccess = /cannot be sent for this event/;
    const { view } = await open({
      [`GET ${FOLLOW}`]: follow({ leads: [60], deliverable: false, code: 'reminders_no_access' }),
    });
    const once = () =>
      [...(view.host.querySelectorAll('[role="status"]') ?? [])].filter((n) =>
        noAccess.test(n.textContent ?? ''),
      ).length;
    expect(once()).toBe(1);
    await click(control());
    expect(once()).toBe(1);
    await view.unmount();
    const second = await open({
      [`GET ${FOLLOW}`]: follow({ deliverable: false, code: 'reminders_no_access' }),
    });
    expect(
      [...second.view.host.querySelectorAll('[role="status"]')].filter((n) =>
        noAccess.test(n.textContent ?? ''),
      ).length,
    ).toBe(0); // not following, panel closed: the control alone
    await click(control());
    expect(
      [...document.querySelectorAll('[role="status"]')].filter((n) =>
        noAccess.test(n.textContent ?? ''),
      ).length,
    ).toBe(1);
    await second.view.unmount();
  });

  it('shows the next due time in the viewer zone and names both zones', async () => {
    const before = process.env.TZ;
    process.env.TZ = 'America/New_York';
    try {
      const { view } = await open({
        [`GET ${FOLLOW}`]: follow({ leads: [60], next_due: { '60': '2026-07-01T09:00:00Z' } }),
      });
      await click(control());
      const text = view.host.textContent ?? '';
      expect(text).toContain('5:00'); // 09:00 UTC is 05:00 in New York, not 9:00
      expect(text).not.toContain('9:00 AM');
      expect(text).toContain("browser's time zone (America/New_York)");
      expect(text).toContain("event's zone is Europe/Vienna");
      await view.unmount();
    } finally {
      if (before === undefined) delete process.env.TZ;
      else process.env.TZ = before;
    }
  });
});

describe('RemindMe on an event that is over', () => {
  it('offers no control, and says why in one line', async () => {
    const { view } = await open({ [`GET ${FOLLOW}`]: follow({ over: true }) });
    expect(control()).toBeNull();
    const note = view.host.querySelector('[data-testid="remind-over"]');
    expect(note?.textContent).toBe(
      'This event is over, so there is nothing left to remind you of.',
    );
    await view.unmount();
  });

  it('keeps the control for someone already following, so they can stop', async () => {
    const { view } = await open({ [`GET ${FOLLOW}`]: follow({ over: true, leads: [60] }) });
    expect(control()?.textContent).toContain('Reminding');
    expect(view.host.querySelector('[data-testid="remind-over"]')).toBeNull();
    await view.unmount();
  });

  it('is unchanged while an occurrence is coming', async () => {
    const { view } = await open({ [`GET ${FOLLOW}`]: follow({ over: false }) });
    expect(control()?.textContent).toBe('Remind me');
    await view.unmount();
  });
});
