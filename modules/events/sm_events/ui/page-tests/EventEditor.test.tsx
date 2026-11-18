// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { eventDetail, field, flush, refusal, stubFetch, unprocessable } from './support';
import { act, click, mount, pickTab, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { router } = await import('@inertiajs/react');
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
  vi.mocked(router.visit).mockClear();
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
const tab = (view: { all: <T extends Element>(s: string) => T[] }, text: string) =>
  view.all('[role="tab"]').find((el) => el.textContent?.includes(text));

async function fillBasics(view: Awaited<ReturnType<typeof mount>>) {
  await setValue(field('text-en-title'), 'Concert');
  await setValue(field('event-start'), '2026-07-01T10:00');
  await setValue(field('event-end'), '2026-07-01T11:00');
  return view;
}

describe('EventEditor: create', () => {
  it('creates an event with texts in two locales', async () => {
    const calls = stubFetch({ [`POST ${API}`]: () => eventDetail({ id: 'new1' }) });
    const view = await mount(<EventEditor {...props} />);
    await fillBasics(view);
    await pickTab(tab(view, 'German'));
    await click(view.button('Add a text in German'));
    await setValue(field('text-de-title'), 'Konzert');
    await setValue(field('text-de-slug'), 'konzert-live');
    await submitForm();
    const body = calls.find((c) => c.method === 'POST')?.body as Body;
    expect(body.calendar_id).toBe('c1');
    expect(body.times).toEqual({
      all_day: false,
      timezone: 'Europe/Vienna',
      start: '2026-07-01T10:00',
      end: '2026-07-01T11:00',
    });
    expect(Object.keys(body.texts)).toEqual(['en', 'de']);
    expect(body.texts.de).toMatchObject({ title: 'Konzert', slug: 'konzert-live' });
    expect(body.texts.en.slug).toBeNull();
    expect(body.rrule).toBeNull();
    expect(router.visit).toHaveBeenCalledWith('/admin/events/edit/new1', { replace: true });
    await view.unmount();
  });

  it('all-day switches inputs and sends dates', async () => {
    const calls = stubFetch({ [`POST ${API}`]: () => eventDetail({ id: 'new1' }) });
    const view = await mount(<EventEditor {...props} />);
    await fillBasics(view);
    expect(field('event-start').type).toBe('datetime-local');
    await click(document.getElementById('event-all-day'));
    expect(field('event-start').type).toBe('date');
    await setValue(field('event-start'), '2026-07-01');
    await setValue(field('event-end'), '2026-07-03');
    await submitForm();
    const body = calls.find((c) => c.method === 'POST')?.body as Body;
    expect(body.times).toEqual({
      all_day: true,
      timezone: 'Europe/Vienna',
      start: '2026-07-01',
      end: '2026-07-03',
    });
    await view.unmount();
  });

  it('shows the UTC offset of the clock being edited', async () => {
    stubFetch({});
    const view = await mount(<EventEditor {...props} />);
    await setValue(field('event-start'), '2026-07-01T10:00');
    expect(view.host.textContent).toContain('Europe/Vienna clock (UTC+02:00)');
    await setValue(field('event-start'), '2026-01-15T10:00');
    expect(view.host.textContent).toContain('Europe/Vienna clock (UTC+01:00)');
    await view.unmount();
  });

  it('requires a title in the default language before any request', async () => {
    const calls = stubFetch({});
    const view = await mount(<EventEditor {...props} />);
    await submitForm();
    expect(calls).toHaveLength(0);
    expect(document.getElementById('text-en-title-error')?.textContent).toBe(
      'This field is required.',
    );
    expect(field('text-en-title').getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(field('text-en-title'));
    await view.unmount();
  });

  it('server field error lands on the de title and moves focus there', async () => {
    stubFetch({ [`POST ${API}`]: () => unprocessable(['texts', 'de', 'title']) });
    const view = await mount(<EventEditor {...props} />);
    await fillBasics(view);
    await pickTab(tab(view, 'German'));
    await click(view.button('Add a text in German'));
    await setValue(field('text-de-title'), 'x');
    await pickTab(tab(view, 'English'));
    await submitForm();
    expect(tab(view, 'German')?.getAttribute('aria-selected')).toBe('true');
    expect(document.getElementById('text-de-title-error')?.textContent).toContain('Enter a title');
    expect(field('text-de-title').getAttribute('aria-describedby')).toBe('text-de-title-error');
    expect(document.activeElement).toBe(field('text-de-title'));
    await view.unmount();
  });

  it('places coded refusals at their input', async () => {
    stubFetch({ [`POST ${API}`]: () => refusal(422, 'invalid_local_time') });
    const view = await mount(<EventEditor {...props} />);
    await fillBasics(view);
    await submitForm();
    expect(document.getElementById('event-start-error')?.textContent).toContain('does not exist');
    expect(field('event-start').getAttribute('aria-invalid')).toBe('true');
    expect(document.activeElement).toBe(field('event-start'));
    await view.unmount();
    vi.unstubAllGlobals();
    stubFetch({ [`POST ${API}`]: () => refusal(409, 'slug_taken') });
    const second = await mount(<EventEditor {...props} />);
    await fillBasics(second);
    await setValue(field('text-en-slug'), 'concert');
    await submitForm();
    expect(document.getElementById('text-en-slug-error')?.textContent).toContain('already in use');
    await second.unmount();
  });

  it('a 422 for a field the form does not show adds the generic message', async () => {
    stubFetch({ [`POST ${API}`]: () => unprocessable(['type']) });
    const view = await mount(<EventEditor {...props} />);
    await fillBasics(view);
    await submitForm();
    expect(view.find('form [role="alert"]')?.textContent).toContain('Check the fields');
    await view.unmount();
  });
});

describe('EventEditor: edit', () => {
  const route = (extra = {}) => ({ [`GET ${API}/e1`]: () => eventDetail(extra) });

  it('loads the event and saves with expected_revision', async () => {
    const calls = stubFetch({
      ...route({ revision: 4 }),
      [`PATCH ${API}/e1`]: () => eventDetail({ revision: 5 }),
    });
    const view = await mount(<EventEditor {...props} event_id="e1" />);
    await flush();
    expect(field('text-en-title').value).toBe('Concert');
    expect(document.getElementById('text-en-description')?.innerHTML).toBe(
      '<p>Doors at <strong>nine</strong></p>',
    );
    expect(view.button('Save')?.hasAttribute('disabled')).toBe(true);
    await setValue(field('text-en-title'), 'Concert II');
    await submitForm();
    const patch = calls.find((c) => c.method === 'PATCH')?.body as Body;
    expect(patch.expected_revision).toBe(4);
    expect(patch.texts.en.title).toBe('Concert II');
    expect(patch.times).toBeUndefined();
    await view.unmount();
  });

  it('default locale tab cannot be removed, another can', async () => {
    const calls = stubFetch({
      ...route({
        texts: {
          en: {
            slug: 'c',
            title: 'Concert',
            summary: null,
            description: '',
            seo_title: null,
            seo_description: null,
            noindex: false,
          },
          de: {
            slug: 'k',
            title: 'Konzert',
            summary: null,
            description: '',
            seo_title: null,
            seo_description: null,
            noindex: false,
          },
        },
      }),
      [`PATCH ${API}/e1`]: () => eventDetail(),
    });
    const view = await mount(<EventEditor {...props} event_id="e1" />);
    await flush();
    expect(view.button('Remove this language')).toBeUndefined();
    await pickTab(tab(view, 'German'));
    await click(view.button('Remove this language'));
    await submitForm();
    const patch = calls.find((c) => c.method === 'PATCH')?.body as Body;
    expect(patch.texts).toEqual({ de: null });
    await view.unmount();
  });

  it('says the event is gone on a 404, with no form', async () => {
    stubFetch({ [`GET ${API}/e1`]: () => refusal(404, 'not_found') });
    const view = await mount(<EventEditor {...props} event_id="e1" />);
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toBe('This event no longer exists.');
    expect(view.find('form')).toBeNull();
    await view.unmount();
  });

  it('shows a load failure with Retry, not an empty form', async () => {
    let fail = true;
    stubFetch({ [`GET ${API}/e1`]: () => (fail ? refusal(500, 'x') : eventDetail()) });
    const view = await mount(<EventEditor {...props} event_id="e1" />);
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toContain('The request failed');
    expect(view.find('form')).toBeNull();
    fail = false;
    await click(view.button('Retry'));
    await flush();
    expect(field('text-en-title').value).toBe('Concert');
    await view.unmount();
  });

  it('is read-only with a reason for a writer without the publish right', async () => {
    stubFetch(route({ status: 'published', locked: true, can_publish: false }));
    const view = await mount(<EventEditor {...props} event_id="e1" />);
    await flush();
    expect(view.host.textContent).toContain('Published: only a publisher can change it.');
    expect(field('text-en-title').disabled).toBe(true);
    expect(view.button('Save')).toBeUndefined();
    expect(view.find('iframe')?.getAttribute('sandbox')).toBe('');
    await view.unmount();
  });

  it('explains a view-only caller', async () => {
    stubFetch(route({ can_write: false }));
    const view = await mount(<EventEditor {...props} event_id="e1" />);
    await flush();
    expect(view.host.textContent).toContain('You can view this event but not change it.');
    await view.unmount();
  });
});
