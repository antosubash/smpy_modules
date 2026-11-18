// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { eventDetail, field, flush, stubFetch } from './support';
import { act, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
// biome-ignore lint/suspicious/noExplicitAny: the tests read request bodies loosely
type Body = Record<string, any>;
const API = '/api/events/events';
const props = {
  event_id: null as string | null,
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en', 'de'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};

beforeEach(() => history.replaceState(null, '', '/admin/events/edit/new?calendar=c1'));
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

const submitForm = async () => {
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
};
async function fillBasics() {
  await setValue(field('text-en-title'), 'Concert');
  await setValue(field('event-start'), '2026-07-01T10:00');
  await setValue(field('event-end'), '2026-07-01T11:00');
}

describe('EventEditor: an incomplete repeat end', () => {
  it('blocks the save with a message at the date input and focuses it', async () => {
    const calls = stubFetch({ [`POST ${API}`]: () => eventDetail({ id: 'new1' }) });
    const view = await mount(<EventEditor {...props} />);
    await fillBasics();
    await setValue(field('event-rrule-mode'), 'WEEKLY');
    await setValue(field('event-rrule-end'), 'until');
    await setValue(field('event-rrule-until'), '');
    await submitForm();
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0);
    expect(document.getElementById('event-rrule-until-error')?.textContent).toBe(
      'This field is required.',
    );
    expect(document.activeElement).toBe(field('event-rrule-until'));
    await setValue(field('event-rrule-until'), '2026-12-31');
    await submitForm();
    const body = calls.find((c) => c.method === 'POST')?.body as Body;
    expect(body.rrule).toBe('FREQ=WEEKLY;UNTIL=20261231;BYDAY=WE');
    await view.unmount();
  });
});
