import { describe, expect, it } from 'vitest';

import { mapRevision } from './mapRevision';

const at = (id: string, lat: number | null, lng: number | null) => ({ id, lat, lng });

describe('mapRevision (review of QA retest 2)', () => {
  it('changes when a located image is replaced by another, at the same counts', () => {
    const before = mapRevision([at('a', 1, 2), at('b', null, null)]);
    expect(mapRevision([at('c', 1, 2), at('b', null, null)])).not.toBe(before);
  });

  it('changes when an image moves or gains a location', () => {
    const before = mapRevision([at('a', 1, 2)]);
    expect(mapRevision([at('a', 1, 3)])).not.toBe(before);
    expect(mapRevision([at('a', null, null)])).not.toBe(before);
  });

  it('stays put for the same located images, whatever the order or the unlocated ones', () => {
    const before = mapRevision([at('a', 1, 2), at('b', 3, 4)]);
    expect(mapRevision([at('b', 3, 4), at('a', 1, 2), at('x', null, null)])).toBe(before);
  });
});
