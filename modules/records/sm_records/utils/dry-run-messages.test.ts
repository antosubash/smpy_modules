import { describe, expect, it } from 'vitest';

import { humanizeDryRunMessage } from './dry-run-messages';

function fakeT(_key: string, opts: { defaultValue: string }): string {
  return opts.defaultValue;
}

describe('humanizeDryRunMessage — U13a: a required-but-missing value reads as what it is', () => {
  it('rewrites pydantic\'s "Field required"', () => {
    expect(humanizeDryRunMessage(fakeT, 'Field required')).toBe(
      'required, but this record has no value for it',
    );
  });

  it('rewrites "Input should be a valid <type>" for several types', () => {
    for (const type of ['date', 'datetime', 'integer', 'string', 'boolean']) {
      expect(humanizeDryRunMessage(fakeT, `Input should be a valid ${type}`)).toBe(
        'required, but this record has no value for it',
      );
    }
  });

  it('leaves a message it does not recognise alone', () => {
    expect(humanizeDryRunMessage(fakeT, 'String should have at most 200 characters')).toBe(
      'String should have at most 200 characters',
    );
  });

  it('tolerates surrounding whitespace', () => {
    expect(humanizeDryRunMessage(fakeT, '  Field required  ')).toBe(
      'required, but this record has no value for it',
    );
  });
});
