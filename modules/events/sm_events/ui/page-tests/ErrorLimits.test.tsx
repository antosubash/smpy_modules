// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { eventDetail, field, flush, stubFetch } from './support';
import { act, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
const API = '/api/events/events';
const props = {
  event_id: null as string | null,
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};

beforeEach(() => history.replaceState(null, '', '/admin/events/edit/new?calendar=c1'));
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

const refuse = (code: string, fieldPath: string) =>
  Response.json({ detail: 'Refused', code, field: fieldPath }, { status: 422 });
const submitForm = async () => {
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
};
const error = (id: string) => document.getElementById(`${id}-error`)?.textContent;
const count = (text: string) => (document.body.textContent?.split(text).length ?? 1) - 1;
const LIMITS =
  'An event can last at most 366 days; when it repeats, each occurrence at most 31 days.';

describe('limits and fields named in a refusal', () => {
  it('duration_too_long says how long an event may last', async () => {
    stubFetch({ [`POST ${API}`]: () => refuse('duration_too_long', 'times.end') });
    const view = await mount(<EventEditor {...props} />);
    await setValue(field('text-en-title'), 'Concert');
    await submitForm();
    expect(error('event-end')).toBe(LIMITS);
    await view.unmount();
  });

  it('start_not_in_rule marks the start', async () => {
    stubFetch({ [`POST ${API}`]: () => refuse('start_not_in_rule', 'times.start') });
    const view = await mount(<EventEditor {...props} />);
    await setValue(field('text-en-title'), 'Concert');
    await submitForm();
    expect(error('event-start')).toContain('Change the start or the rule');
    expect(document.activeElement).toBe(field('event-start'));
    await view.unmount();
  });

  it('a recurring event says it once, not in the preview and at the field', async () => {
    stubFetch({
      [`GET ${API}/e1`]: () => eventDetail({ rrule: 'FREQ=DAILY;COUNT=3', revision: 1 }),
      ['POST /api/events/recurrence/preview']: () => refuse('duration_too_long', 'times.end'),
      [`PATCH ${API}/e1`]: () => refuse('duration_too_long', 'times.end'),
    });
    const view = await mount(<EventEditor {...props} event_id="e1" />);
    await flush(450);
    await setValue(field('text-en-title'), 'Changed');
    await submitForm();
    expect(count(LIMITS)).toBe(1);
    await view.unmount();
  });
});
