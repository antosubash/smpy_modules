import { describe, expect, it } from 'vitest';

import { withCurrentPatched } from './record-types';
import type { TranslationRead } from './types';

function sibling(overrides: Partial<TranslationRead> = {}): TranslationRead {
  return {
    locale: 'de',
    uuid: 'de-uuid',
    status: 'draft',
    display_title: 'Autumn Summit',
    is_deleted: false,
    ...overrides,
  };
}

describe('withCurrentPatched — U20: the Languages panel reflects a just-saved title', () => {
  it('patches the sibling whose locale matches the saved record', () => {
    const list = [sibling({ locale: 'en', uuid: 'en-uuid' }), sibling()];
    const patched = withCurrentPatched(list, {
      locale: 'de',
      uuid: 'de-uuid',
      status: 'published',
      display_title: 'Herbstgipfel',
      is_deleted: false,
    });
    expect(patched.find((s) => s.locale === 'de')).toEqual({
      locale: 'de',
      uuid: 'de-uuid',
      status: 'published',
      display_title: 'Herbstgipfel',
      is_deleted: false,
    });
    // The other locale's entry is untouched.
    expect(patched.find((s) => s.locale === 'en')?.display_title).toBe('Autumn Summit');
  });

  it('leaves the list unchanged when there is no current record (the new-record screen)', () => {
    const list = [sibling()];
    expect(withCurrentPatched(list, null)).toEqual(list);
  });

  it('leaves the list unchanged when current names a locale not in it', () => {
    const list = [sibling({ locale: 'en' })];
    const patched = withCurrentPatched(list, {
      locale: 'fr',
      uuid: 'fr-uuid',
      status: 'draft',
      display_title: 'Bonjour',
      is_deleted: false,
    });
    expect(patched).toEqual(list);
  });
});
