import { describe, expect, it } from 'vitest';

import { disambiguateLabels, opsForFieldType } from './filters';

/**
 * Mirrors `sm_records.index._predicates._ALLOWED` — see that dict for the
 * server-side truth this is checked against (F1).
 */
describe('opsForFieldType', () => {
  it('gives every text-like kind eq/ne/in/contains/starts_with', () => {
    for (const type of ['text', 'select', 'multiselect', 'email', 'url']) {
      expect(opsForFieldType(type)).toEqual(['eq', 'ne', 'in', 'contains', 'starts_with']);
    }
  });

  it('gives boolean only eq/ne', () => {
    expect(opsForFieldType('boolean')).toEqual(['eq', 'ne']);
  });

  it('gives number, integer, date and datetime the full ordered set', () => {
    for (const type of ['number', 'integer', 'date', 'datetime']) {
      expect(opsForFieldType(type)).toEqual(['eq', 'ne', 'in', 'gt', 'gte', 'lt', 'lte']);
    }
  });

  it('gives relation eq/ne/in with no ordering', () => {
    expect(opsForFieldType('relation')).toEqual(['eq', 'ne', 'in']);
  });

  it('returns nothing for a type that cannot be indexed', () => {
    expect(opsForFieldType('json')).toEqual([]);
    expect(opsForFieldType('longtext')).toEqual([]);
    expect(opsForFieldType('media')).toEqual([]);
  });

  it('returns nothing for an unknown type rather than throwing', () => {
    expect(opsForFieldType('nope')).toEqual([]);
  });
});

describe('disambiguateLabels', () => {
  it('leaves unique labels untouched', () => {
    const fields = [
      { key: 'name', label: 'Name' },
      { key: 'status', label: 'Status' },
    ];
    expect(disambiguateLabels(fields)).toEqual(fields);
  });

  it('appends the key to every member of a colliding label', () => {
    expect(
      disambiguateLabels([
        { key: 'order_status', label: 'Status' },
        { key: 'status', label: 'Status' },
        { key: 'name', label: 'Name' },
      ]),
    ).toEqual([
      { key: 'order_status', label: 'Status (order_status)' },
      { key: 'status', label: 'Status (status)' },
      { key: 'name', label: 'Name' },
    ]);
  });

  it('keeps the other properties of a disambiguated field', () => {
    const [first] = disambiguateLabels([
      { key: 'a', label: 'Dup', ops: ['eq'] },
      { key: 'b', label: 'Dup', ops: ['ne'] },
    ]);
    expect(first).toEqual({ key: 'a', label: 'Dup (a)', ops: ['eq'] });
  });
});
