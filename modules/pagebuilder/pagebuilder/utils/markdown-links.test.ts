import { describe, expect, it } from 'vitest';

import { isSafeHref, isSafeImageSrc, splitLinks } from './markdown-links';

describe('splitLinks', () => {
  it('returns plain text as a single text segment', () => {
    expect(splitLinks('just **text**')).toEqual([{ type: 'text', text: 'just **text**' }]);
    expect(splitLinks('')).toEqual([]);
  });

  it('splits links out of the surrounding text, label markers intact', () => {
    expect(splitLinks('see [**docs**](/docs) now')).toEqual([
      { type: 'text', text: 'see ' },
      { type: 'link', label: '**docs**', href: '/docs' },
      { type: 'text', text: ' now' },
    ]);
  });

  it('keeps one level of parentheses in an href', () => {
    expect(splitLinks('[W](https://w.example/A_(b))')).toEqual([
      { type: 'link', label: 'W', href: 'https://w.example/A_(b)' },
    ]);
  });

  it('reads images and linked images', () => {
    expect(splitLinks('![](/a.png)')).toEqual([{ type: 'image', alt: '', src: '/a.png' }]);
    expect(splitLinks('[![A](/a.png)](https://a.example)')).toEqual([
      { type: 'linkedImage', alt: 'A', src: '/a.png', href: 'https://a.example' },
    ]);
  });

  it('leaves an unsafe href or src as literal text', () => {
    for (const markup of [
      '[x](javascript:alert(1))',
      '![x](data:image/svg+xml,x)',
      '[![x](/x.png)](javascript:alert(1))',
      '[![x](javascript:x)](/ok)',
    ]) {
      expect(splitLinks(markup)).toEqual([{ type: 'text', text: markup }]);
    }
  });
});

describe('isSafeHref / isSafeImageSrc', () => {
  it('allows relative and well-known schemes only', () => {
    expect(['/x', '#a', 'https://x', 'mailto:a@b', 'tel:1'].every(isSafeHref)).toBe(true);
    expect(isSafeHref('JavaScript:x')).toBe(false);
    expect(['/a.png', 'a.png', 'http://x/a.png'].every(isSafeImageSrc)).toBe(true);
    expect(isSafeImageSrc('mailto:a@b')).toBe(false);
  });
});
