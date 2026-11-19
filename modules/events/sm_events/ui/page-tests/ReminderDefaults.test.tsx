// @vitest-environment happy-dom
import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { button, calendar, flush, stubFetch, submit } from './support';
import { click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: Calendars } = await import('../../pages/Calendars');
const API = '/api/events/calendars';
const props = { can_create: true, can_manage: false, user_id: 'u1', default_timezone: 'UTC' };

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

const box = (suffix: string) =>
  [...document.querySelectorAll<HTMLElement>('[role="dialog"] [role="checkbox"]')].find((b) =>
    b.id.endsWith(suffix),
  );

describe('calendar reminder defaults', () => {
  it('sends null for the site default and the chosen list otherwise', async () => {
    const calls = stubFetch({
      [`GET ${API}`]: [calendar()],
      [`PATCH ${API}/c1`]: calendar(),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Edit'));
    expect(document.body.textContent).toContain('Reminder times');
    expect(box('-site')?.getAttribute('aria-checked')).toBe('true');
    await submit();
    const first = calls.find((c) => c.method === 'PATCH')?.body as Record<string, unknown>;
    expect(first.default_reminder_minutes).toBeNull();
    await flush();
    await click(button('Edit')); // the dialog closed on save
    await click(box('-site'));
    await click(box('-15'));
    await click(box('-1440'));
    await submit();
    const bodies = calls
      .filter((c) => c.method === 'PATCH')
      .map((c) => c.body as Record<string, unknown>);
    expect(bodies.at(-1)?.default_reminder_minutes).toEqual([15, 1440]);
    await view.unmount();
  });

  it("starts from the calendar's own list", async () => {
    stubFetch({ [`GET ${API}`]: [calendar({ default_reminder_minutes: [60] })] });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Edit'));
    expect(box('-site')?.getAttribute('aria-checked')).toBe('false');
    expect(box('-60')?.getAttribute('aria-checked')).toBe('true');
    expect(box('-15')?.getAttribute('aria-checked')).toBe('false');
    await view.unmount();
  });

  it('is not offered when creating a calendar', async () => {
    stubFetch({ [`GET ${API}`]: [] });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('New calendar'));
    expect(document.body.textContent).not.toContain('Reminder times');
    await view.unmount();
  });
});
