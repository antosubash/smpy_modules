import { describe, expect, it } from 'vitest';

import { isSafeHref, isSafeImageSrc, safeFrameSrc, safeHref, splitLinks } from './markdown-links';

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

  it('rejects a control character browsers would strip in front of a scheme', () => {
    expect(isSafeHref('\u0001javascript:alert(1)')).toBe(false);
    expect(isSafeHref('/x\u007f')).toBe(false);
    expect(isSafeImageSrc('\u001fjavascript:x')).toBe(false);
  });
});

describe('safeHref', () => {
  it('passes an allowed link through unchanged', () => {
    for (const href of [
      '/about',
      '#top',
      '?q=1',
      './x',
      'contact',
      'https://x.example',
      'mailto:a@b',
      'tel:+431',
    ]) {
      expect(safeHref(href)).toBe(href);
    }
  });

  it('turns an unsafe, empty or missing one into the fallback', () => {
    for (const href of [
      'javascript:alert(1)',
      'JAVASCRIPT:x',
      'data:text/html,x',
      'vbscript:x',
      ' javascript:x',
      '\u0001javascript:x',
      '',
      '   ',
      undefined,
      null,
      42,
    ]) {
      expect(safeHref(href)).toBe('#');
    }
    expect(safeHref('javascript:x', '')).toBe('');
    expect(safeHref(undefined, '/')).toBe('/');
  });

  it('sees a scheme behind leading spaces, as a browser does', () => {
    expect(isSafeHref('  javascript:alert(1)')).toBe(false);
    expect(isSafeHref('  /fine')).toBe(true);
  });
});

describe('safeFrameSrc', () => {
  it('loads http(s) and relative sources only', () => {
    for (const src of ['https://x.example/e', 'http://x', '/media/a.mp4', '//cdn.example/v']) {
      expect(safeFrameSrc(src)).toBe(src);
    }
    for (const src of ['javascript:x', 'data:text/html,x', 'mailto:a@b', ' vbscript:x', '', null]) {
      expect(safeFrameSrc(src)).toBe('');
    }
  });
});
