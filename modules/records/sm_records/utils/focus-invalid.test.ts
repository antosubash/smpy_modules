import { describe, expect, it } from 'vitest';

import { firstErrorInDomOrder } from './focus-invalid';

const FIELDS = ['title', 'subtitle', 'body'];

describe('firstErrorInDomOrder — R17: a 422 lands where the client validator would', () => {
  it('picks the topmost field on screen, not the first one the server listed', () => {
    const errors = [{ field: 'body' }, { field: 'title' }];
    expect(firstErrorInDomOrder(errors, FIELDS)).toBe('title');
  });

  it('tolerates the data. prefix the envelope carries', () => {
    expect(firstErrorInDomOrder([{ field: 'data.body' }, { field: 'data.title' }], FIELDS)).toBe(
      'title',
    );
  });

  it('puts status above the fields and slug/position below them', () => {
    expect(firstErrorInDomOrder([{ field: 'title' }, { field: 'status' }], FIELDS)).toBe('status');
    expect(firstErrorInDomOrder([{ field: 'position' }, { field: 'body' }], FIELDS)).toBe('body');
    expect(firstErrorInDomOrder([{ field: 'position' }, { field: 'slug' }], FIELDS)).toBe('slug');
  });

  it('never prefers a key this screen has no input for', () => {
    // `__root__` has nothing to scroll to; the field error does.
    expect(firstErrorInDomOrder([{ field: '__root__' }, { field: 'body' }], FIELDS)).toBe('body');
    expect(firstErrorInDomOrder([{ field: '__root__' }], FIELDS)).toBe('__root__');
  });

  it('answers null for an empty list', () => {
    expect(firstErrorInDomOrder([], FIELDS)).toBeNull();
  });
});
