// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { button, type Call, field, flush, stubFetch, submit } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: Categories } = await import('../../pages/Categories');
const API = '/api/events/categories';
const category = { id: 'a1', slug: 'music', names: { en: 'Music', de: 'Musik' }, color: '#2563eb' };
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

it('renders one labelled name field per content locale, first required', async () => {
  stubFetch({ [`GET ${API}`]: [] });
  const view = await mount(<Categories content_locales={['en', 'de']} />);
  await flush();
  await click(button('New category'));
  for (const locale of ['en', 'de']) {
    expect(document.querySelector(`label[for="category-name-${locale}"]`)?.textContent).toContain(
      locale,
    );
    expect(field(`category-name-${locale}`)).toBeInstanceOf(HTMLInputElement);
  }
  expect(field('category-name-en').hasAttribute('required')).toBe(true);
  expect(field('category-name-de').hasAttribute('required')).toBe(false);
  await view.unmount();
});
it('creates with names keyed by locale and shows the row', async () => {
  let made = false;
  const calls = stubFetch({
    [`GET ${API}`]: () => (made ? [category] : []),
    [`POST ${API}`]: () => {
      made = true;
      return category;
    },
  });
  const view = await mount(<Categories content_locales={['en', 'de']} />);
  await flush();
  await click(button('New category'));
  await setValue(field('category-name-en'), 'Music');
  await setValue(field('category-name-de'), 'Musik');
  await submit();
  expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
    names: { en: 'Music', de: 'Musik' },
    color: '#2563eb',
  });
  expect(view.host.textContent).toContain('Music');
  expect(view.host.textContent).toContain('Musik');
  await view.unmount();
});
it.each([
  ['unknown_locale', 'configured content language'],
  ['slug_taken', 'slug is already in use'],
])('shows %s without closing the dialog', async (code, message) => {
  stubFetch({
    [`GET ${API}`]: [],
    [`POST ${API}`]: Response.json(
      { detail: 'server message', code },
      { status: code === 'slug_taken' ? 409 : 422 },
    ),
  });
  const view = await mount(<Categories content_locales={['en', 'de']} />);
  await flush();
  await click(button('New category'));
  await setValue(field('category-name-en'), 'Music');
  await submit();
  expect(document.querySelector('[role="alert"]')?.textContent).toContain(message);
  expect(field('category-name-en').value).toBe('Music');
  await view.unmount();
});
it('delete asks first, cancellation leaves the category intact', async () => {
  let deleted = false;
  const calls = stubFetch({
    [`GET ${API}`]: () => (deleted ? [] : [category]),
    [`DELETE ${API}/a1`]: () => {
      deleted = true;
      return null;
    },
  });
  const view = await mount(<Categories content_locales={['en', 'de']} />);
  await flush();
  await click(button('Delete'));
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
  expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain('uncategorised');
  await click(button('Cancel'));
  expect(view.host.textContent).toContain('Music');
  await click(button('Delete'));
  const dialog = document.querySelector('[role="alertdialog"]');
  if (!dialog) throw new Error('Missing confirmation');
  await click(button('Delete', dialog));
  await flush();
  expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
  expect(view.host.textContent).not.toContain('Music');
  await view.unmount();
});
it('edits names and colour without attempting to rename the immutable slug', async () => {
  const calls = stubFetch({
    [`GET ${API}`]: [category],
    [`PATCH ${API}/a1`]: (call: Call) => ({ ...category, ...(call.body as object) }),
  });
  const view = await mount(<Categories content_locales={['en', 'de']} />);
  await flush();
  await click(button('Edit'));
  expect(field('category-slug').hasAttribute('readonly')).toBe(true);
  await setValue(field('category-name-de'), 'Klänge');
  await submit();
  expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
    names: { en: 'Music', de: 'Klänge' },
    color: '#2563eb',
  });
  await view.unmount();
});

it('omits blank optional names and keeps an uncoloured category uncoloured', async () => {
  const calls = stubFetch({
    [`GET ${API}`]: [{ ...category, color: null }],
    [`PATCH ${API}/a1`]: { ...category, color: null, names: { en: 'Music' } },
  });
  const view = await mount(<Categories content_locales={['en', 'de']} />);
  await flush();
  await click(button('Edit'));
  await setValue(field('category-name-de'), '');
  await submit();
  expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
    names: { en: 'Music' },
    color: null,
  });
  await view.unmount();
});
