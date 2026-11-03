import { describe, expect, it } from 'vitest';

import { cells, itemKey, lines, row } from './lines';

describe('lines', () => {
  it('trims and drops blanks, so a blank line is spacing rather than an item', () => {
    expect(lines('  one  \n\n two \n   \nthree')).toEqual(['one', 'two', 'three']);
  });

  it('treats an unset field as no items rather than one empty one', () => {
    expect(lines(undefined)).toEqual([]);
    expect(lines('')).toEqual([]);
    expect(lines('   \n  ')).toEqual([]);
  });
});

describe('cells', () => {
  it('splits and trims to the requested width', () => {
    expect(cells('2019 | the survey began', 2)).toEqual(['2019', 'the survey began']);
  });

  it('pads a short row, so a source with no link is still a source', () => {
    expect(cells('Interview, March 2024', 2)).toEqual(['Interview, March 2024', '']);
    expect(cells('https://example.org/a', 3)).toEqual(['https://example.org/a', '', '']);
  });

  it('folds the overflow back into the last cell rather than truncating it', () => {
    // The realistic case: a caption containing a pipe. Dropping the tail would
    // lose the end of a writer's sentence with nothing to show for it.
    expect(cells('https://x/a.png | alt | before | after', 3)).toEqual([
      'https://x/a.png',
      'alt',
      'before | after',
    ]);
  });
});

describe('row', () => {
  it('splits a table row on pipes', () => {
    expect(row('Site | Sensors | Live')).toEqual(['Site', 'Sensors', 'Live']);
  });

  it('tolerates a row pasted in Markdown style', () => {
    // Otherwise `| a | b |` gains an empty cell at each end and the table
    // renders two columns wider than it reads in the field.
    expect(row('| North | 12 |')).toEqual(['North', '12']);
  });

  it('keeps an intentionally empty cell in the middle', () => {
    expect(row('North |  | 12')).toEqual(['North', '', '12']);
  });
});

describe('itemKey', () => {
  it('distinguishes two identical items', () => {
    // Two identical bullets are a real thing to write; keying on the text alone
    // makes React treat the second as a duplicate of the first.
    expect(itemKey('Own table', 0)).not.toBe(itemKey('Own table', 1));
  });
});
