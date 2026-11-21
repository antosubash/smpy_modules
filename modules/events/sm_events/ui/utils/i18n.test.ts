import { describe, expect, it } from 'vitest';

import { keys, translate } from './i18n';

describe('the events catalogue', () => {
  it('derives its key tree from locales/en.json', () => {
    expect(keys.events.permission_group).toBe('events.permission_group');
  });

  it('translates a key to its English text through the configured catalogue', () => {
    expect(translate('events.permission_group')).toBe('Events');
  });
});
