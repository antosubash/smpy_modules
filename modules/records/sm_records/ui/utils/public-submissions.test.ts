import { describe, expect, it } from 'vitest';

import { withoutInternal } from './public-submissions';

describe('withoutInternal — what a revision preview shows (#101)', () => {
  const fields = [
    { key: 'sm_email', system: 'readonly' as const },
    { key: 'sm_nonce', system: 'internal' as const },
    { key: 'name' },
  ];

  it('leaves internal system values out and keeps everything else', () => {
    const data = { sm_email: 'a@x.io', sm_nonce: 'secret', name: 'Ada', _orphaned: { x: 1 } };
    expect(withoutInternal(data, fields)).toEqual({
      sm_email: 'a@x.io',
      name: 'Ada',
      _orphaned: { x: 1 },
    });
    expect(data.sm_nonce).toBe('secret');
  });

  it('returns an ordinary type’s snapshot as it is', () => {
    const data = { name: 'Ada' };
    expect(withoutInternal(data, [{ key: 'name' }])).toBe(data);
  });
});
