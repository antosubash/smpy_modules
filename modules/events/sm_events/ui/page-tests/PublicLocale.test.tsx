// @vitest-environment happy-dom

import { updateI18n } from '@simple-module-py/i18n';
import { afterEach, expect, it, vi } from 'vitest';
import { makeT } from '../utils/PageLocale';
import { indexProps, item } from './public-support';
import { mount, ready } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: PublicNotFound } = await import('../../pages/PublicNotFound');
const { default: PublicIndex } = await import('../../pages/PublicIndex');

afterEach(() => {
  document.body.innerHTML = '';
  updateI18n({ locale: 'en', messages: {} });
});

const notFound = (locale: string) => (
  <PublicNotFound locale={locale} index_url="/x/" suggestions={[item({ key: 'a' })]} />
);

it('a German page shows German headings while the console language is English', async () => {
  updateI18n({ locale: 'en', messages: {} });
  const view = await mount(notFound('de'));
  await ready(view, 'h1');
  expect(view.find('h1')?.textContent).toBe('Seite nicht gefunden');
  expect(document.documentElement.lang).toBe('de');
}, 30000);

it('an English page is English whatever the console says', async () => {
  updateI18n({ locale: 'de', messages: {} });
  const view = await mount(notFound('en'));
  expect(view.find('h1')?.textContent).toBe('Page not found');
});

it('a language without a catalogue reads English', async () => {
  const view = await mount(notFound('fr'));
  expect(view.find('h1')?.textContent).toBe('Page not found');
  expect(document.documentElement.lang).toBe('fr');
});

it('placeholders and plural forms follow the page language', () => {
  const de = { 'events.x.n_one': '{count} Termin', 'events.x.n_other': '{count} Termine' };
  const t = makeT(de, 'de');
  expect(t('events.x.n', { count: 1 })).toBe('1 Termin');
  expect(t('events.x.n', { count: 3 })).toBe('3 Termine');
  expect(makeT({}, 'de')('events.public.index.page_of', { page: 2, count: 5 })).toBe('Page 2 of 5');
  expect(makeT({}, 'de')('events.public.index.page_of')).toBe('Page {page} of {count}');
  expect(makeT({}, 'de')('events.no.such.key')).toBe('events.no.such.key');
  // An English page has no catalogue of its own: its singular is English's, not the plural's.
  const unresolved = 'events.blocks.editor_hint.unresolved';
  expect(makeT({}, 'en')(unresolved, { count: 1 })).toBe(
    '1 chosen calendar is not public or no longer exists.',
  );
  expect(makeT({}, 'en')(unresolved, { count: 2 })).toBe(
    '2 chosen calendars are not public or no longer exist.',
  );
});

it('the index, grid labels and pager read the page language too', async () => {
  const view = await mount(<PublicIndex {...indexProps({ locale: 'de', groups: [] })} />);
  await ready(view, 'main, section, nav, div');
  expect(view.host.textContent).toContain('Keine kommenden Veranstaltungen.');
});
