// @vitest-environment happy-dom
import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { eventDetail, field, flush, stubFetch } from './support';
import { act, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
const props = {
  event_id: null as string | null,
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en', 'de'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

describe('EventEditor: prefill from the calendar', () => {
  it('fills times and title, and creates with them', async () => {
    const calls = stubFetch({ 'POST /api/events/events': () => eventDetail({ id: 'new1' }) });
    const prefill = {
      all_day: false,
      start: '2026-07-01T10:00',
      end: '2026-07-01T11:00',
      title: 'Team sync',
    };
    const view = await mount(<EventEditor {...props} prefill={prefill} />);
    expect(field('event-start').value).toBe('2026-07-01T10:00');
    expect(field('event-end').value).toBe('2026-07-01T11:00');
    expect(field('text-en-title').value).toBe('Team sync');
    await act(async () => {
      document
        .querySelector('form')
        ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
      times: {
        all_day: false,
        timezone: 'Europe/Vienna',
        start: '2026-07-01T10:00',
        end: '2026-07-01T11:00',
      },
      texts: { en: { title: 'Team sync' } },
    });
    await view.unmount();
  });

  it('fills an all-day span with dates', async () => {
    const prefill = { all_day: true, start: '2026-08-01', end: '2026-08-03', title: null };
    const view = await mount(<EventEditor {...props} prefill={prefill} />);
    expect(field('event-start').type).toBe('date');
    expect(field('event-start').value).toBe('2026-08-01');
    expect(field('event-end').value).toBe('2026-08-03');
    expect(field('text-en-title').value).toBe('');
    await view.unmount();
  });

  it('does not count a prefilled form as unsaved changes', async () => {
    const prefill = { all_day: null, start: null, end: null, title: 'Team sync' };
    const view = await mount(<EventEditor {...props} prefill={prefill} />);
    expect(field('text-en-title').value).toBe('Team sync');
    // Typing on top of it is a change; the prefill itself is not.
    expect(view.find('[role="alertdialog"]')).toBeNull();
    await view.unmount();
  });

  it('ignores a prefill on an existing event', async () => {
    stubFetch({ 'GET /api/events/events/e1': eventDetail() });
    const view = await mount(
      <EventEditor
        {...props}
        event_id="e1"
        prefill={{ all_day: false, start: '2030-01-01T10:00', end: '2030-01-01T11:00', title: 'X' }}
      />,
    );
    await flush();
    expect(field('event-start').value).not.toBe('2030-01-01T10:00');
    await view.unmount();
  });
});
