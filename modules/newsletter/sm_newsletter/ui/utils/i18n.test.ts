import { describe, expect, it } from 'vitest';

import { keys, translate } from './i18n';

describe('the newsletter catalogue', () => {
  it('derives its key tree from locales/en.json', () => {
    expect(keys.newsletter.permission_group).toBe('newsletter.permission_group');
  });

  it('translates a key to its English text through the configured catalogue', () => {
    expect(translate('newsletter.permission_group')).toBe('Newsletter');
  });

  it('substitutes the single-brace placeholders of the import strings', () => {
    expect(translate(keys.newsletter.import.progress, { processed: 3, total: 9 })).toBe(
      '3 of 9 rows processed',
    );
  });
});
