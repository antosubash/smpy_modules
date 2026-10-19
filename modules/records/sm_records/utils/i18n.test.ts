import { describe, expect, it } from 'vitest';

import { englishText, keys } from './i18n';

describe('englishText', () => {
  it('leaves a placeholder the caller did not supply, as i18next does', () => {
    expect(englishText(keys.records.widget.field_link_template)).toBe(
      'Link template ({slug} or {uuid}; blank = no link)',
    );
  });

  it('fills the placeholders it is given', () => {
    expect(englishText(keys.records.bulk.done_trash, { count: 3 })).toBe(
      '3 records moved to the Trash',
    );
  });
});
