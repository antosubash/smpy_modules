import { describe, expect, it } from 'vitest';

import { recordDisplayTitle, shortUuid } from './record-title';

describe('shortUuid', () => {
  it('takes the first 8 characters, marked as shortened', () => {
    expect(shortUuid('3f2a1c9e84b34e0e9a1b2c3d4e5f6789')).toBe('3f2a1c9e…');
  });
});

describe('recordDisplayTitle — U5: an accessible name for a record with no title', () => {
  it('is the display title when there is one', () => {
    expect(
      recordDisplayTitle(
        { display_title: 'Autumn Summit', uuid: '3f2a1c9e84b34e0e9a1b2c3d4e5f6789' },
        { label: 'Tag' },
      ),
    ).toBe('Autumn Summit');
  });

  it('falls back to the type label and the short uuid when the title is empty', () => {
    expect(
      recordDisplayTitle(
        { display_title: '', uuid: '3f2a1c9e84b34e0e9a1b2c3d4e5f6789' },
        { label: 'Tag' },
      ),
    ).toBe('Tag 3f2a1c9e…');
  });
});
