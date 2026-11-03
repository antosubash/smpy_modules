import { describe, expect, it } from 'vitest';

import { parseChoiceList } from './ChoicesEditor';

/** The bulk-entry box behind R9's "Paste a list": a `select` with fifty
 *  choices is not something anyone types one row at a time. */
describe('parseChoiceList', () => {
  it('uses a bare line as both value and label', () => {
    expect(parseChoiceList('red\ngreen')).toEqual([
      { value: 'red', label: 'red' },
      { value: 'green', label: 'green' },
    ]);
  });

  it('splits on | or = and trims both sides', () => {
    expect(parseChoiceList(' red | Red \ngreen=Green')).toEqual([
      { value: 'red', label: 'Red' },
      { value: 'green', label: 'Green' },
    ]);
  });

  it('skips blank lines and lines with no value', () => {
    expect(parseChoiceList('\n  \nred\n= Orphan label')).toEqual([{ value: 'red', label: 'red' }]);
  });

  it('falls back to the value when the label side is empty', () => {
    expect(parseChoiceList('red |')).toEqual([{ value: 'red', label: 'red' }]);
  });
});
