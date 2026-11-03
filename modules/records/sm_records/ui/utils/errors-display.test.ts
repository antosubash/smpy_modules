import { describe, expect, it } from 'vitest';

import { displayFieldKey } from './errors-display';

describe('displayFieldKey — R11: the wire prefix is not a field name', () => {
  it('strips the data. envelope prefix a payload error carries', () => {
    expect(displayFieldKey('data.title')).toBe('title');
  });

  it('leaves a bare key — and an envelope key — alone', () => {
    expect(displayFieldKey('title')).toBe('title');
    expect(displayFieldKey('slug')).toBe('slug');
    expect(displayFieldKey('__root__')).toBe('__root__');
  });

  it('strips only the leading occurrence', () => {
    expect(displayFieldKey('data.data.x')).toBe('data.x');
  });
});
