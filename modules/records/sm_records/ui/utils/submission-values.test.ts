import { describe, expect, it } from 'vitest';

import { missingRequired, payloadFor, valuesFor } from './submission-values';
import type { SubmissionDefinition, SubmissionField } from './submissions-form-api';

function field(key: string, type: string, extra: Partial<SubmissionField> = {}): SubmissionField {
  return {
    key,
    type,
    label: key,
    help: null,
    required: false,
    choices: [],
    constraints: {},
    default: null,
    ...extra,
  };
}

const FIELDS = [
  field('name', 'text', { required: true }),
  field('count', 'integer'),
  field('price', 'number'),
  field('when', 'datetime'),
  field('tags', 'multiselect', { default: ['a'] }),
  field('agree', 'boolean', { required: true }),
  field('kind', 'select', { default: 'general' }),
];

const DEF = { fields: FIELDS } as unknown as SubmissionDefinition;

describe('submission values', () => {
  it('starts from the defaults and keeps typed values of fields that still exist', () => {
    const start = valuesFor(DEF);
    expect(start).toMatchObject({ name: '', tags: ['a'], agree: false, kind: 'general' });
    const kept = valuesFor(DEF, { name: 'Ada', gone: 'x', agree: 'oops' });
    expect(kept.name).toBe('Ada');
    expect(kept.agree).toBe(false);
    expect('gone' in kept).toBe(false);
  });

  it('leaves an empty field out and converts numbers and datetimes', () => {
    const values = {
      ...valuesFor(DEF),
      name: 'Ada',
      count: '3',
      price: '2,5',
      when: '2026-03-04T10:00',
      tags: [],
    };
    const data = payloadFor(FIELDS, values);
    expect(data).toMatchObject({
      name: 'Ada',
      count: 3,
      price: 2.5,
      agree: false,
      kind: 'general',
    });
    expect(data.when).toBe(new Date('2026-03-04T10:00').toISOString());
    expect('tags' in data).toBe(false);
    expect(payloadFor(FIELDS, { ...values, count: 'abc' }).count).toBe('abc');
  });

  it('a required field is missing until filled, a required box until ticked', () => {
    expect(missingRequired(FIELDS, valuesFor(DEF))).toEqual(['name', 'agree']);
    expect(missingRequired(FIELDS, { ...valuesFor(DEF), name: ' x', agree: true })).toEqual([]);
  });
});
