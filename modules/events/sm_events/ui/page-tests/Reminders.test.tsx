// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { resetReminderStatus } from '../utils/api-reminders';
import { flush, stubFetch } from './support';
import { click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: Reminders } = await import('../../pages/Reminders');

const MINE = '/api/events/reminders/mine';
const DELIVERY = '/api/events/reminders/delivery';
const counts = { sent: 3, failed: { send_failed: 1 }, unfinished: 0 };
const visible = {
  follow_id: 'f1',
  hidden: false,
  event_id: 'e1',
  title: 'Garden talk',
  lang: 'en',
  calendar: { id: 'c1', name: 'Town', color: '#2563eb' },
  leads: [60, 1440],
  next_start: '2026-07-01T10:00:00Z',
  deliverable: true,
};
const opaque = {
  follow_id: 'f2',
  hidden: true,
  event_id: null,
  title: null,
  lang: null,
  calendar: null,
  leads: [],
  next_start: null,
  deliverable: false,
};
const page = (items: unknown[], over = {}) => ({
  items,
  total: items.length,
  hidden: items.filter((i) => (i as { hidden: boolean }).hidden).length,
  page: 1,
  page_size: 20,
  counts,
  ...over,
});
const props = { is_manager: false, settings_url: '/admin/settings/' };

afterEach(() => {
  vi.unstubAllGlobals();
  resetReminderStatus();
  document.body.innerHTML = '';
});

const removeButton = (name: RegExp) =>
  [...document.querySelectorAll('button')].find((b) =>
    name.test(b.getAttribute('aria-label') ?? ''),
  );

describe('Reminders page', () => {
  it('lists the reminders and removes one by its follow id', async () => {
    let gone = false;
    const calls = stubFetch({
      [`GET ${MINE}`]: () => page(gone ? [] : [visible]),
      'DELETE /api/events/reminders/follows/f1': () => {
        gone = true;
        return null;
      },
    });
    const view = await mount(<Reminders {...props} />);
    await flush();
    expect(view.host.textContent).toContain('Garden talk');
    expect(view.host.textContent).toContain('Town');
    expect(view.host.textContent).toContain('1 h, 1 day');
    await click(removeButton(/Remove reminders for Garden talk/));
    await flush();
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
    expect(view.host.textContent).toContain('You are not following any events');
    await view.unmount();
  });

  it('shows an event the user can no longer see as an opaque row they can remove', async () => {
    const calls = stubFetch({
      [`GET ${MINE}`]: page([visible, opaque]),
      'DELETE /api/events/reminders/follows/f2': null,
    });
    const view = await mount(<Reminders {...props} />);
    await flush();
    const row = view.host.querySelector('[data-testid="hidden-follow"]');
    expect(row?.textContent).toContain('An event you can no longer see');
    expect(view.host.textContent).toContain('remove them here');
    await click(removeButton(/Remove reminders for An event you can no longer see/));
    expect(calls.some((c) => c.url.endsWith('/follows/f2'))).toBe(true);
    await view.unmount();
  });

  it('pages, and says what a failed reminder means and that the scheduler cannot be seen', async () => {
    const calls = stubFetch({
      [`GET ${MINE}`]: (call: { url: string }) =>
        page([visible], { total: 45, page: call.url.includes('page=2') ? 2 : 1 }),
    });
    const view = await mount(<Reminders {...props} />);
    await flush();
    expect(view.host.textContent).toContain('Page 1 of 3');
    await click([...document.querySelectorAll('button')].find((b) => b.textContent === 'Next'));
    await flush();
    expect(calls.some((c) => c.url.includes('page=2'))).toBe(true);
    expect(view.host.textContent).toContain('is not retried');
    expect(view.host.textContent).toContain('cannot tell whether it is running');
    await view.unmount();
  });

  it("shows the cap note at the cap and the caller's own counts", async () => {
    stubFetch({ [`GET ${MINE}`]: page([visible], { total: 200 }) });
    const view = await mount(<Reminders {...props} />);
    await flush();
    expect(view.host.textContent).toContain('at most 200 events');
    expect(view.host.querySelector('[data-testid="my-counts"]')?.textContent).toContain(
      '3 sent, 1 failed, 0 unfinished',
    );
    await view.unmount();
  });

  it('marks a reminder the worker could not verify', async () => {
    stubFetch({ [`GET ${MINE}`]: page([{ ...visible, deliverable: false }]) });
    const view = await mount(<Reminders {...props} />);
    await flush();
    expect(view.host.textContent).toContain(
      'cannot be sent for this event with your current access',
    );
    await view.unmount();
  });

  it('shows the delivery card to managers only', async () => {
    stubFetch({
      [`GET ${MINE}`]: page([]),
      [`GET ${DELIVERY}`]: {
        enabled: true,
        available: true,
        reason: null,
        defaults: [60],
        window_days: 30,
        counts: { sent: 5, failed: { send_timeout: 2 }, unfinished: 1 },
      },
    });
    const staff = await mount(<Reminders {...props} />);
    await flush();
    expect(staff.host.querySelector('[data-testid="delivery-card"]')).toBeNull();
    await staff.unmount();
    const manager = await mount(<Reminders is_manager settings_url="/admin/settings/" />);
    await flush();
    const card = manager.host.querySelector('[data-testid="delivery-card"]');
    expect(card?.textContent).toContain('Sent: 5');
    expect(card?.textContent).toContain('Mail server did not answer in time: 2');
    expect(card?.textContent).toContain('Unfinished: 1');
    expect(card?.querySelector('a')?.getAttribute('href')).toBe('/admin/settings/');
    await manager.unmount();
  });

  it.each([
    ['disabled', 'switched off'],
    ['no_public_base_url', 'public address'],
    ['no_mail_transport', 'No mail transport'],
    ['console_mail', 'console backend'],
  ])('has a sentence for the reason %s', async (reason, words) => {
    stubFetch({
      [`GET ${MINE}`]: page([]),
      [`GET ${DELIVERY}`]: {
        enabled: reason !== 'disabled',
        available: false,
        reason,
        defaults: [60],
        window_days: 30,
        counts: { sent: 0, failed: {}, unfinished: 0 },
      },
    });
    const view = await mount(<Reminders is_manager settings_url="/admin/settings/" />);
    await flush();
    expect(view.host.querySelector('[data-testid="delivery-card"]')?.textContent).toContain(words);
    await view.unmount();
  });
});
