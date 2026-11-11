import { describe, expect, it } from 'vitest';

import { safeJsonLd } from './jsonLd';

describe('safeJsonLd', () => {
  const doc = {
    name: '</script><script>alert(1)</script>',
    headline: 'a <!-- comment --> b',
    mixed: '</SCRIPT>',
  };

  it('leaves no "<" for the HTML parser to act on', () => {
    expect(safeJsonLd(doc)).not.toContain('<');
  });

  it('is valid JSON that round-trips to the original document', () => {
    expect(JSON.parse(safeJsonLd(doc))).toEqual(doc);
  });
});
