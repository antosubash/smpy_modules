import { describe, expect, it } from 'vitest';

import { clampFeedLimit, safeHref } from './feedProps';

describe('clampFeedLimit', () => {
  it.each([
    [4, 4],
    [4.5, 4],
    [4.99, 4],
    [0, 1],
    [0.5, 1],
    [-3, 1],
    [12, 12],
    [12.9, 12],
    [13, 12],
    [1000, 12],
    ['7.5', 7],
    [Number.NaN, 4],
    [Number.POSITIVE_INFINITY, 4],
    [undefined, 4],
    [null, 4],
    ['abc', 4],
  ])('%s -> %s', (input, expected) => {
    const out = clampFeedLimit(input);
    expect(out).toBe(expected);
    expect(Number.isInteger(out)).toBe(true);
  });
});

describe('safeHref', () => {
  it.each([
    ['/x', '/x'],
    ['/news/?page=2', '/news/?page=2'],
    ['https://x', 'https://x'],
    ['http://x', 'http://x'],
    ['HTTPS://x', 'HTTPS://x'],
    ['#a', '#a'],
    ['mailto:a@b.c', 'mailto:a@b.c'],
    ['tel:+123', 'tel:+123'],
    ['  /x  ', '/x'],
    ['news', 'news'],
    ['./news', './news'],
    ['../news', '../news'],
    ['x/y', 'x/y'],
    ['x/y:z', 'x/y:z'],
    ['?page=2', '?page=2'],
    ['?a=b:c', '?a=b:c'],
    ['#a:b', '#a:b'],
    ['./a:b', './a:b'],
  ])('keeps %s', (input, expected) => {
    expect(safeHref(input)).toBe(expected);
  });

  it.each([
    '//evil.com',
    '/\\evil.com',
    'javascript:alert(1)',
    'JaVaScRiPt:alert(1)',
    ' javascript:alert(1)',
    '\tjavascript:alert(1)',
    'java\nscript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'ftp://x',
    'java\tscript:alert(1)',
    'data:,x',
    'javascript://%0aalert(1)',
    'a:b/c',
    '\\\\evil.com',
    '\\evil.com',
    '  //evil.com',
    '',
    '   ',
  ])('drops %j', (input) => {
    expect(safeHref(input)).toBe('');
  });

  it('drops non-strings', () => {
    expect(safeHref(undefined)).toBe('');
    expect(safeHref(null)).toBe('');
  });
});
