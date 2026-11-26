// @vitest-environment happy-dom
import { updateI18n } from '@simple-module-py/i18n';
import { beforeAll, expect, it } from 'vitest';
import { ApiError, errorText } from './api';
import { loadCatalogue, makeT } from './PageLocale';
import { parseRule, summarise } from './recurrence';

// What an anonymous German visitor has since #417: the page's own catalogue, and a
// shared catalogue without this module.
let german: ReturnType<typeof makeT>;
beforeAll(async () => {
  german = makeT(await loadCatalogue('de'), 'de');
  updateI18n({ locale: 'en', messages: {} });
});

it('a recurrence sentence uses the translator it is given', () => {
  const rule = parseRule('FREQ=WEEKLY;BYDAY=MO', '2026-07-06T10:00', 'Europe/Vienna');
  if (!rule) throw new Error('rule did not parse');
  expect(summarise(rule, '2026-07-06T10:00', 'de', german)).toMatch(/^Jede Woche am Montag/);
  // Without one it is the console's language, here English with nothing loaded.
  expect(summarise(rule, '2026-07-06T10:00', 'de')).toMatch(/^Every week/);
});

it('a request failure uses the translator it is given', () => {
  expect(errorText(new Error('boom'), undefined, german)).toBe(
    'Die Anfrage ist fehlgeschlagen. Versuchen Sie es erneut.',
  );
  expect(errorText(new ApiError(403, 'forbidden'), undefined, german)).toBe(
    'Sie haben keine Berechtigung für diese Aktion.',
  );
  expect(errorText(new ApiError(429, 'rate_limited', [], 5), undefined, german)).not.toMatch(
    /requests|Too many/i,
  );
  expect(errorText(new Error('boom'))).toMatch(/failed|wrong|try again/i);
});
