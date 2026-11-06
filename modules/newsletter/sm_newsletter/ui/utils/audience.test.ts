import { describe, expect, it } from 'vitest';

import { type AudienceChoice, formatAudience, parseAudience } from './audience';

describe('audience', () => {
  it.each<[string, AudienceChoice]>([
    ['all', { kind: 'all' }],
    ['tag:vip', { kind: 'tag', tag: 'vip' }],
    ['segment:12', { kind: 'segment', segmentId: 12 }],
  ])('round-trips %s', (raw, choice) => {
    expect(parseAudience(raw)).toEqual(choice);
    expect(formatAudience(choice)).toBe(raw);
  });

  it('keeps a colon inside a tag', () => {
    expect(parseAudience('tag:a:b')).toEqual({ kind: 'tag', tag: 'a:b' });
  });

  it('reads an unknown form as the whole list', () => {
    expect(parseAudience('segment:x')).toEqual({ kind: 'all' });
    expect(parseAudience('whatever')).toEqual({ kind: 'all' });
  });
});
