// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { field, flush, stubFetch } from './support';
import { act, click, mount, pickTab, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
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

const refuse = (status: number, code: string, fieldPath?: string, extra = {}) =>
  Response.json(
    { detail: 'Refused', code, ...(fieldPath ? { field: fieldPath } : {}), ...extra },
    { status },
  );
const submitForm = async () => {
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
};
async function filled(response: () => Response) {
  stubFetch({ [`POST ${API}`]: response });
  const view = await mount(<EventEditor {...props} />);
  await setValue(field('text-en-title'), 'Concert');
  return view;
}
const error = (id: string) => document.getElementById(`${id}-error`)?.textContent;

describe('a refusal lands on the input the server names', () => {
  it('invalid_local_time at the end, not the start', async () => {
    const view = await filled(() => refuse(422, 'invalid_local_time', 'times.end'));
    await submitForm();
    expect(error('event-end')).toContain('does not exist');
    expect(error('event-start') ?? '').toBe('');
    expect(document.activeElement).toBe(field('event-end'));
    await view.unmount();
  });

  it('slug_taken marks the language that failed, with both slugs typed', async () => {
    const view = await filled(() => refuse(409, 'slug_taken', 'texts.en.slug'));
    await setValue(field('text-en-slug'), 'one');
    await pickTab(
      [...document.querySelectorAll('[role="tab"]')].find((t) => t.textContent?.includes('German')),
    );
    await click(
      [...document.querySelectorAll('button')].find((b) =>
        b.textContent?.includes('Add a text in German'),
      ),
    );
    await setValue(field('text-de-title'), 'Konzert');
    await setValue(field('text-de-slug'), 'zwei');
    await submitForm();
    // The newest typed slug is German, but the server said English failed.
    expect(error('text-en-slug')).toBeTruthy();
    expect(error('text-de-slug') ?? '').toBe('');
    await view.unmount();
  });

  it('description_too_long lands at the description of its language', async () => {
    const view = await filled(() => refuse(422, 'description_too_long', 'texts.en.description'));
    await submitForm();
    expect(error('text-en-description')).toContain('too long');
    await view.unmount();
  });

  it('a 422 loc on texts.<l>.description gets its own message', async () => {
    const view = await filled(() =>
      Response.json(
        { detail: [{ loc: ['body', 'texts', 'en', 'description'], msg: 'bad', type: 'x' }] },
        { status: 422 },
      ),
    );
    await submitForm();
    expect(error('text-en-description')).toContain('too long');
    await view.unmount();
  });

  it('a slug conflict that names no language stays a general message when two slugs changed', async () => {
    const view = await filled(() => refuse(409, 'slug_taken'));
    await setValue(field('text-en-slug'), 'one');
    await pickTab(
      [...document.querySelectorAll('[role="tab"]')].find((t) => t.textContent?.includes('German')),
    );
    await click(
      [...document.querySelectorAll('button')].find((b) =>
        b.textContent?.includes('Add a text in German'),
      ),
    );
    await setValue(field('text-de-title'), 'Konzert');
    await setValue(field('text-de-slug'), 'zwei');
    await submitForm();
    expect(error('text-en-slug') ?? '').toBe('');
    expect(error('text-de-slug') ?? '').toBe('');
    expect(document.querySelector('form [role="alert"]')?.textContent).toBeTruthy();
    await view.unmount();
  });
});

describe('rate limits outside the people search', () => {
  it('a saved 429 says requests, not searches', async () => {
    const view = await filled(() => refuse(429, 'rate_limited', undefined, { retry_after: 5 }));
    await submitForm();
    const text = document.querySelector('form [role="alert"]')?.textContent;
    expect(text).toBe('Too many requests. Try again in 5 seconds.');
    await view.unmount();
  });
});

describe('the list hint', () => {
  it('names the time zone the dates are days in', async () => {
    const { default: Events } = await import('../../pages/Events');
    stubFetch({ [`GET ${API}`]: { items: [], total: 0, page: 1, page_size: 50 } });
    const view = await mount(
      <Events calendars={[]} categories={[]} can_create={false} content_locales={['en']} />,
    );
    await flush();
    expect(view.host.textContent).toMatch(/Dates are days in your time zone \(.+\)\./);
    await view.unmount();
  });
});
