import { describe, expect, it } from 'vitest';

import { emptyRule, ruleComplete, valueInput } from './rules';
import type { ListField } from './types';

function field(type: string, over: Partial<ListField> = {}): ListField {
  return {
    key: 'f',
    label: 'F',
    type,
    many: false,
    choices: [],
    system: false,
    ops: ['is'],
    ...over,
  };
}

describe('valueInput', () => {
  it('offers choices for any, all and none', () => {
    for (const op of ['any', 'all', 'none'] as const) {
      expect(valueInput(field('select', { many: true }), op)).toBe('choices');
    }
    expect(valueInput(field('select'), 'any')).toBe('choices');
  });

  it('offers one choice for a select with is / is_not', () => {
    const f = field('select', { choices: [{ value: 'a', label: 'A' }] });
    expect(valueInput(f, 'is')).toBe('choice');
    expect(valueInput(f, 'is_not')).toBe('choice');
  });

  it('follows the field type otherwise', () => {
    expect(valueInput(field('text'), 'contains')).toBe('text');
    expect(valueInput(field('email'), 'starts_with')).toBe('text');
    expect(valueInput(field('url'), 'is')).toBe('text');
    expect(valueInput(field('number'), 'gt')).toBe('number');
    expect(valueInput(field('integer'), 'lte')).toBe('number');
    expect(valueInput(field('date'), 'before')).toBe('date');
    expect(valueInput(field('datetime'), 'since')).toBe('date');
    expect(valueInput(field('boolean'), 'is')).toBe('boolean');
  });
});

describe('emptyRule', () => {
  it('takes the first op and an empty value of the right shape', () => {
    expect(emptyRule(field('text', { ops: ['is', 'contains'] }))).toEqual({
      field: 'f',
      op: 'is',
      value: '',
    });
    expect(emptyRule(field('select', { many: true, ops: ['any', 'all', 'none'] }))).toEqual({
      field: 'f',
      op: 'any',
      value: [],
    });
  });
});

describe('ruleComplete', () => {
  it('needs a non-blank value', () => {
    expect(ruleComplete({ field: 'f', op: 'is', value: '' })).toBe(false);
    expect(ruleComplete({ field: 'f', op: 'is', value: '  ' })).toBe(false);
    expect(ruleComplete({ field: 'f', op: 'is', value: 'x' })).toBe(true);
    expect(ruleComplete({ field: 'f', op: 'any', value: [] })).toBe(false);
    expect(ruleComplete({ field: 'f', op: 'any', value: ['a'] })).toBe(true);
    expect(ruleComplete({ field: '', op: 'is', value: 'x' })).toBe(false);
  });
});
