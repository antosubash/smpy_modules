// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, errorText, isOrphaning, isStale } from '../utils/api';
import {
  clearOverride,
  createEvent,
  listEvents,
  restoreEvent,
  transition,
  trashEvent,
  updateEvent,
} from '../utils/api-events';
import { stubFetch } from './support';

const API = '/api/events/events';

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
});

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    return e as ApiError;
  }
  throw new Error('expected a failure');
}

describe('events API client', () => {
  it('sends expected_revision on update and maps 409 stale', async () => {
    const calls = stubFetch({
      [`PATCH ${API}/e1`]: () =>
        Response.json({ detail: 'Changed', code: 'stale' }, { status: 409 }),
    });
    const error = await failure(updateEvent('e1', { expected_revision: 3, cancelled: true }));
    expect(calls[0]?.body).toEqual({ expected_revision: 3, cancelled: true });
    expect(isStale(error)).toBe(true);
    expect(isOrphaning(error)).toBe(false);
    expect(errorText(error)).toBe('Someone else changed this event since you opened it.');
  });

  it('maps every refusal the API names to its own text', async () => {
    for (const code of ['publish_required', 'has_sub_events', 'invalid_transition']) {
      const text = errorText(new ApiError(code === 'publish_required' ? 403 : 409, code));
      expect(text).not.toBe('The request failed. Please try again.');
    }
    expect(errorText(new ApiError(422, 'invalid_local_time'))).toContain('does not exist');
  });

  it('quotes the revision on trash, restore, workflow and override calls', async () => {
    const calls = stubFetch({
      [`DELETE ${API}/e1`]: null,
      [`POST ${API}/e1/restore`]: {},
      [`POST ${API}/e1/approve`]: {},
      [`DELETE ${API}/e1/overrides/7`]: null,
    });
    await trashEvent('e1', 4);
    await restoreEvent('e1', 5);
    await transition('e1', 'approve', {
      expected_revision: 6,
      publish_at_local: '2026-07-01T09:00',
    });
    await clearOverride('e1', 7, 8);
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      `DELETE ${API}/e1?expected_revision=4`,
      `POST ${API}/e1/restore`,
      `POST ${API}/e1/approve`,
      `DELETE ${API}/e1/overrides/7?expected_revision=8`,
    ]);
    expect(calls[1]?.body).toEqual({ expected_revision: 5 });
    expect(calls[2]?.body).toEqual({
      expected_revision: 6,
      publish_at_local: '2026-07-01T09:00',
    });
  });

  it('builds the list query without empty filters', async () => {
    const calls = stubFetch({
      [`GET ${API}`]: { items: [], total: 0, page: 2, page_size: 50 },
      [`POST ${API}`]: { id: 'new' },
    });
    await listEvents({ calendar: 'c1', status: 'scheduled', q: '', trashed: false, page: 2 });
    expect(calls[0]?.url).toBe(`${API}?calendar=c1&status=scheduled&page=2`);
    await createEvent({
      calendar_id: 'c1',
      times: {
        all_day: false,
        timezone: 'UTC',
        start: '2026-07-01T10:00',
        end: '2026-07-01T11:00',
      },
      texts: {
        en: {
          title: 'A',
          slug: null,
          summary: null,
          description: '',
          seo_title: null,
          seo_description: null,
          noindex: false,
        },
      },
      rrule: null,
      cancelled: false,
      attendance_mode: 'in_person',
      venue_name: null,
      address: null,
      online_url: null,
      latitude: null,
      longitude: null,
      category_id: null,
      organiser: null,
      image: null,
      registration_url: null,
    });
    expect(calls[1]?.method).toBe('POST');
  });
});
