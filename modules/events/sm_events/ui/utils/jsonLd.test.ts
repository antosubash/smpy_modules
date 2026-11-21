import { describe, expect, it } from 'vitest';
import { safeJsonLd } from './jsonLd';

const LS = String.fromCharCode(0x2028);
const PS = String.fromCharCode(0x2029);

describe('safeJsonLd', () => {
  it('cannot close or open an element', () => {
    const out = safeJsonLd({ name: '</script><script>alert(1)</script>' });
    expect(out).not.toMatch(/[<>&]/);
    expect(JSON.parse(out).name).toBe('</script><script>alert(1)</script>');
  });
  it('escapes the JavaScript line separators and ampersands', () => {
    const doc = { a: `x${LS}y${PS}z & <!-- ]]>` };
    const out = safeJsonLd(doc);
    expect(out).not.toContain(LS);
    expect(out).not.toContain(PS);
    expect(out).not.toMatch(/[<>&]/);
    expect(JSON.parse(out)).toEqual(doc);
  });
  it('leaves ordinary documents alone', () => {
    expect(safeJsonLd({ n: 1, s: 'a' })).toBe('{"n":1,"s":"a"}');
  });
});
