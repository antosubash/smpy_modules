// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { button, calendar, field, flush, stubFetch, submit } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
const { default: Calendars } = await import('../../pages/Calendars');
const API = '/api/events/calendars';
const props = { can_create: true, can_manage: false, user_id: 'u1', default_timezone: 'UTC' };

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

function expectAnnounced(input: HTMLElement, errorId: string) {
  expect(document.activeElement).toBe(input);
  expect(input.getAttribute('aria-invalid')).toBe('true');
  expect(input.getAttribute('aria-describedby')).toBe(errorId);
  const message = document.getElementById(errorId);
  expect(message?.getAttribute('role')).toBe('alert');
  expect(message?.textContent).not.toBe('');
}

describe('a failed save moves focus to the first invalid field', () => {
  it('after the client-side check, on the name', async () => {
    stubFetch({ [`GET ${API}`]: [] });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('New calendar'));
    await submit();
    expectAnnounced(field('calendar-name'), 'calendar-name-error');
    await view.unmount();
  });
  it('after a 422 from the server, on the first field it names', async () => {
    stubFetch({
      [`GET ${API}`]: [calendar()],
      [`PATCH ${API}/c1`]: Response.json(
        {
          detail: [
            { loc: ['body', 'default_timezone'], msg: 'bad' },
            { loc: ['body', 'slug'], msg: 'bad' },
          ],
        },
        { status: 422 },
      ),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Edit'));
    await setValue(field('calendar-slug'), 'x');
    await submit();
    // The form order decides, not the order of the server's entries.
    expectAnnounced(field('calendar-slug'), 'calendar-slug-error');
    expect(field('calendar-timezone').getAttribute('aria-invalid')).toBe('true');
    await view.unmount();
  });
});
