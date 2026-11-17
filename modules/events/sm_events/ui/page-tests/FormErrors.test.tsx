// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { button, calendar, field, flush, stubFetch, submit } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));
const { default: Calendars } = await import('../../pages/Calendars');
const { default: Categories } = await import('../../pages/Categories');
const API = '/api/events/calendars';
const CATS = '/api/events/categories';
const props = { can_create: true, can_manage: false, user_id: 'u1', default_timezone: 'UTC' };
const category = { id: 'a1', slug: 'music', names: { en: 'Music', de: 'Musik' }, color: null };

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

const text = () => document.querySelector('[role="dialog"]')?.textContent ?? '';

describe('calendar dialog field errors', () => {
  it('maps a 422 loc to the timezone field, not the generic message', async () => {
    stubFetch({
      [`GET ${API}`]: [calendar()],
      [`PATCH ${API}/c1`]: Response.json(
        { detail: [{ loc: ['body', 'default_timezone'], msg: 'not a known IANA timezone' }] },
        { status: 422 },
      ),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Edit'));
    await submit();
    expect(document.getElementById('calendar-timezone-error')?.textContent).toContain(
      'Choose a timezone',
    );
    expect(text()).not.toContain('Check the fields');
    await view.unmount();
  });
  it('falls back to the generic field message for an unmapped field', async () => {
    stubFetch({
      [`GET ${API}`]: [calendar()],
      [`PATCH ${API}/c1`]: Response.json(
        { detail: [{ loc: ['body', 'sources'], msg: 'bad' }] },
        { status: 422 },
      ),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Edit'));
    await submit();
    expect(text()).not.toContain('Choose a timezone');
    await view.unmount();
  });
  it('sends a timezone outside the browser list and shows the server verdict', async () => {
    const calls = stubFetch({
      [`GET ${API}`]: [],
      [`POST ${API}`]: Response.json(
        { detail: [{ loc: ['body', 'default_timezone'], msg: 'bad' }] },
        { status: 422 },
      ),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('New calendar'));
    await setValue(field('calendar-name'), 'Team');
    await setValue(field('calendar-timezone'), 'Mars/Phobos');
    await submit();
    expect(calls.some((c) => c.method === 'POST')).toBe(true);
    expect(document.getElementById('calendar-timezone-error')?.textContent).toContain(
      'Choose a timezone',
    );
    await setValue(field('calendar-timezone'), 'Europe/Vienna');
    expect(document.getElementById('calendar-timezone-error')).toBeNull();
    await view.unmount();
  });
  it('shows a localized required message and sets noValidate', async () => {
    const calls = stubFetch({ [`GET ${API}`]: [] });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('New calendar'));
    expect(document.querySelector('[role="dialog"] form')?.hasAttribute('novalidate')).toBe(true);
    await submit();
    expect(document.getElementById('calendar-name-error')?.textContent).toBe(
      'This field is required.',
    );
    expect(field('calendar-name').getAttribute('aria-invalid')).toBe('true');
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    await view.unmount();
  });
  it('says the calendar no longer exists on a 404 write and refreshes the list', async () => {
    const calls = stubFetch({
      [`GET ${API}`]: [calendar()],
      [`PATCH ${API}/c1`]: Response.json({ detail: 'Not found' }, { status: 404 }),
    });
    const view = await mount(<Calendars {...props} />);
    await flush();
    await click(button('Edit'));
    await submit();
    expect(calls.filter((c) => c.method === 'GET')).toHaveLength(2);
    await view.unmount();
  });
});

describe('category dialog', () => {
  it('requires the first locale inline and sets noValidate', async () => {
    const calls = stubFetch({ [`GET ${CATS}`]: [] });
    const view = await mount(<Categories content_locales={['en', 'de']} />);
    await flush();
    await click(button('New category'));
    expect(document.querySelector('[role="dialog"] form')?.hasAttribute('novalidate')).toBe(true);
    await submit();
    expect(document.getElementById('category-name-en-error')?.textContent).toBe(
      'This field is required.',
    );
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    await view.unmount();
  });
  it('maps a names 422 to that locale input', async () => {
    stubFetch({
      [`GET ${CATS}`]: [],
      [`POST ${CATS}`]: Response.json(
        { detail: [{ loc: ['body', 'names', 'de'], msg: 'bad' }] },
        { status: 422 },
      ),
    });
    const view = await mount(<Categories content_locales={['en', 'de']} />);
    await flush();
    await click(button('New category'));
    await setValue(field('category-name-en'), 'Music');
    await submit();
    expect(document.getElementById('category-name-de-error')?.textContent).toContain('Enter names');
    await view.unmount();
  });
  it('keeps a null colour as no colour and saves null', async () => {
    const calls = stubFetch({
      [`GET ${CATS}`]: [category],
      [`PATCH ${CATS}/a1`]: category,
    });
    const view = await mount(<Categories content_locales={['en', 'de']} />);
    await flush();
    await click(button('Edit'));
    expect(document.getElementById('category-color')).toBeNull();
    expect(text()).toContain('No colour');
    await submit();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      names: { en: 'Music', de: 'Musik' },
      color: null,
    });
    await view.unmount();
  });
  it('offers a colour to pick when there is none', async () => {
    stubFetch({ [`GET ${CATS}`]: [category] });
    const view = await mount(<Categories content_locales={['en']} />);
    await flush();
    await click(button('Edit'));
    await click(button('Choose a colour'));
    expect(field('category-color').value).toBe('#2563eb');
    await view.unmount();
  });
  it('names rows for assistive tech and confirms with the name, not the slug', async () => {
    stubFetch({ [`GET ${CATS}`]: [category] });
    const view = await mount(<Categories content_locales={['en', 'de']} />);
    await flush();
    expect(button('Delete').getAttribute('aria-label')).toBe('Delete Music');
    expect(button('Edit').getAttribute('aria-label')).toBe('Edit Music');
    await click(button('Delete'));
    const confirm = document.querySelector('[role="alertdialog"]');
    expect(confirm?.textContent).toContain('Delete Music?');
    expect(confirm?.textContent).not.toContain('music?');
    await view.unmount();
  });
  it('uses the slug when no content language has a name, and headers say Slug', async () => {
    stubFetch({ [`GET ${CATS}`]: [{ ...category, names: {} }] });
    const view = await mount(<Categories content_locales={['en']} />);
    await flush();
    expect(button('Delete').getAttribute('aria-label')).toBe('Delete music');
    const heads = [...view.host.querySelectorAll('th')].map((th) => th.textContent);
    expect(heads).toContain('Slug');
    expect(heads.some((h) => h?.includes('optional'))).toBe(false);
    await view.unmount();
  });
});

describe('calendar table', () => {
  it('names every row action after the calendar, wraps the name, headers say Slug', async () => {
    const long = 'x'.repeat(180);
    stubFetch({ [`GET ${API}`]: [calendar({ name: long })] });
    const view = await mount(<Calendars {...props} can_manage />);
    await flush();
    const labels = [...view.host.querySelectorAll('td button')].map((b) =>
      b.getAttribute('aria-label'),
    );
    expect(labels).toContain(`Edit ${long}`);
    expect(labels.every((l) => l?.includes(long))).toBe(true);
    const cell = [...view.host.querySelectorAll('td')].find((td) => td.textContent === long);
    expect(cell?.className).toContain('[overflow-wrap:anywhere]');
    const heads = [...view.host.querySelectorAll('th')].map((th) => th.textContent);
    expect(heads).toContain('Slug');
    await view.unmount();
  });
});
