// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { utcOffsetAt } from '../utils/datetime';
import { eventDetail, flush, stubFetch } from './support';
import { mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
const API = '/api/events/events';
const props = {
  event_id: 'e1',
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

describe('utcOffsetAt', () => {
  it('is the event zone offset at that instant, not the browser one', () => {
    expect(utcOffsetAt('2026-03-28T09:00:00Z', 'Europe/Vienna')).toBe('UTC+01:00');
    expect(utcOffsetAt('2026-03-30T08:00:00Z', 'Europe/Vienna')).toBe('UTC+02:00');
    expect(utcOffsetAt('2026-07-01T00:00:00Z', 'America/St_Johns')).toBe('UTC-02:30');
    expect(utcOffsetAt('nonsense', 'Europe/Vienna')).toBeNull();
    expect(utcOffsetAt('2026-07-01T00:00:00Z', 'Not/AZone')).toBeNull();
  });
});

describe('the recurrence preview', () => {
  it('shows each occurrence with its own offset across a clock change', async () => {
    stubFetch({
      [`GET ${API}/e1`]: () => eventDetail({ rrule: 'FREQ=DAILY;COUNT=2', revision: 1 }),
      ['POST /api/events/recurrence/preview']: () => ({
        occurrences: [
          {
            start: '2026-03-28T09:00:00Z',
            end: '2026-03-28T10:00:00Z',
            start_local: '2026-03-28T10:00',
            end_local: '2026-03-28T11:00',
          },
          {
            start: '2026-03-30T08:00:00Z',
            end: '2026-03-30T09:00:00Z',
            start_local: '2026-03-30T10:00',
            end_local: '2026-03-30T11:00',
          },
        ],
        recurrence_until: null,
        orphaned: [],
      }),
    });
    const view = await mount(<EventEditor {...props} />);
    await flush(450);
    const rows = [...document.querySelectorAll('section[aria-label] ul li')].map(
      (li) => li.textContent,
    );
    expect(rows[0]).toContain('28 Mar 2026, 10:00(UTC+01:00)');
    expect(rows[1]).toContain('30 Mar 2026, 10:00(UTC+02:00)');
    await view.unmount();
  });
});
