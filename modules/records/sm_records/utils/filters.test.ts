import { describe, expect, it } from 'vitest';

import {
  defaultFilterValue,
  disambiguateLabels,
  filterKind,
  normaliseFilterValue,
  opsForFieldType,
} from './filters';

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

describe('filterKind — R8/M12', () => {
  it('sends each field type to the control that can express its values', () => {
    expect(filterKind('flag', 'boolean')).toBe('boolean');
    expect(filterKind('due', 'date')).toBe('date');
    expect(filterKind('seen_at', 'datetime')).toBe('datetime');
    expect(filterKind('author', 'relation')).toBe('relation');
    expect(filterKind('title', 'text')).toBe('text');
    // U11: select/multiselect present as a closed choice set everywhere
    // else in the module — the filter used to be the one place that
    // demanded the stored value through free text instead.
    expect(filterKind('tier', 'select')).toBe('select');
    expect(filterKind('tags', 'multiselect')).toBe('select');
  });

  it('keeps the two fixed columns with closed value sets on their own', () => {
    expect(filterKind('status')).toBe('status');
    expect(filterKind('locale')).toBe('locale');
    expect(filterKind('display_title')).toBe('text');
  });
});

describe('normaliseFilterValue — a select never desyncs from its options', () => {
  it('falls back for a value the control has no option for', () => {
    expect(normaliseFilterValue('boolean', 'maybe', [])).toBe('true');
    expect(normaliseFilterValue('status', 'archived', [])).toBe('draft');
    expect(normaliseFilterValue('locale', 'fr', ['en', 'de'])).toBe('en');
    // U11: a stale/hand-edited `banana` falls back to the field's first
    // choice, the same as every other closed-set kind — not a silent
    // zero-result free-text value.
    expect(normaliseFilterValue('select', 'banana', [], ['CA', 'NY'])).toBe('CA');
  });

  it('keeps a value the control can show, and leaves free text alone', () => {
    expect(normaliseFilterValue('boolean', 'false', [])).toBe('false');
    expect(normaliseFilterValue('status', 'published', [])).toBe('published');
    expect(normaliseFilterValue('locale', 'de', ['en', 'de'])).toBe('de');
    expect(normaliseFilterValue('text', 'anything at all', [])).toBe('anything at all');
    expect(normaliseFilterValue('datetime', '2026-01-15T10:30:00+00:00', [])).toBe(
      '2026-01-15T10:30:00+00:00',
    );
    expect(normaliseFilterValue('select', 'NY', [], ['CA', 'NY'])).toBe('NY');
  });

  it('starts a freshly chosen field on the first option its control offers', () => {
    expect(defaultFilterValue('boolean', [])).toBe('true');
    expect(defaultFilterValue('status', [])).toBe('draft');
    expect(defaultFilterValue('locale', ['en', 'de'])).toBe('en');
    expect(defaultFilterValue('date', [])).toBe('');
    expect(defaultFilterValue('relation', [])).toBe('');
    expect(defaultFilterValue('select', [], ['CA', 'NY'])).toBe('CA');
    // No choices configured yet — the same empty-set fallback `locale`
    // gets with a single-locale install.
    expect(defaultFilterValue('select', [], [])).toBe('');
  });
});
