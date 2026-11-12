import { describe, expect, it } from 'vitest';

import { parseAddresses } from './addresses';

describe('parseAddresses', () => {
  it('splits on lines, commas and semicolons, trims, lower-cases and dedupes', () => {
    expect(parseAddresses(' A@x.org,b@x.org;\nc@x.org\n\na@X.org ')).toEqual([
      'a@x.org',
      'b@x.org',
      'c@x.org',
    ]);
  });

  it('returns nothing for blank input', () => {
    expect(parseAddresses(' \n , ')).toEqual([]);
  });
});
