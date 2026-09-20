import { describe, expect, it } from 'vitest';
import { buildRecordHref, formatPublicValue } from './format';
import type { FieldMetaEntry } from './types';

function meta(type: string, overrides: Partial<FieldMetaEntry> = {}): FieldMetaEntry {
  return { key: 'f', type, label: 'F', choices: [], ...overrides };
}

describe('formatPublicValue', () => {
  it('renders null/undefined as a dash regardless of type', () => {
    expect(formatPublicValue(meta('text'), null)).toBe('—');
    expect(formatPublicValue(meta('number'), undefined)).toBe('—');
  });

  it('renders booleans as ✓/–', () => {
    expect(formatPublicValue(meta('boolean'), true)).toBe('✓');
    expect(formatPublicValue(meta('boolean'), false)).toBe('–');
  });

  it('renders number/integer verbatim (no float round trip)', () => {
    // `number` arrives as a string on the wire (design §7.3) — formatting
    // must not run it through parseFloat/String.
    expect(formatPublicValue(meta('number'), '9.99000')).toBe('9.99000');
    expect(formatPublicValue(meta('integer'), 42)).toBe('42');
  });

  it('formats a date at UTC midnight, independent of the viewer zone', () => {
    // en-US medium date formatting is locale-dependent in shape but not in
    // which calendar day it names; assert the day survives, not the exact
    // string, so this test isn't coupled to the CI runner's ICU data.
    const out = formatPublicValue(meta('date'), '2026-01-15');
    expect(out).toContain('2026');
    expect(out).not.toBe('2026-01-15');
  });

  it('formats a datetime', () => {
    const out = formatPublicValue(meta('datetime'), '2026-01-15T10:30:00Z');
    expect(out).toContain('2026');
  });

  it('falls back to the raw string for an unparseable date/datetime', () => {
    expect(formatPublicValue(meta('date'), 'not-a-date')).toBe('not-a-date');
  });

  it('maps a select value through its choices, falling back to the raw value', () => {
    const field = meta('select', { choices: [{ value: 'a', label: 'Alpha' }] });
    expect(formatPublicValue(field, 'a')).toBe('Alpha');
    expect(formatPublicValue(field, 'orphaned')).toBe('orphaned');
  });

  it('joins multiselect values through their choices', () => {
    const field = meta('multiselect', {
      choices: [
        { value: 'a', label: 'Alpha' },
        { value: 'b', label: 'Beta' },
      ],
    });
    expect(formatPublicValue(field, ['a', 'b'])).toBe('Alpha, Beta');
    expect(formatPublicValue(field, [])).toBe('—');
  });

  it('renders a relation as its stored type:uuid, never expanded', () => {
    expect(formatPublicValue(meta('relation'), { type: 'author', uuid: 'abc-123' })).toBe(
      'author:abc-123',
    );
  });

  it('joins a to-many relation the same way', () => {
    const value = [
      { type: 'author', uuid: 'a1' },
      { type: 'author', uuid: 'a2' },
    ];
    expect(formatPublicValue(meta('relation'), value)).toBe('author:a1, author:a2');
  });

  it('truncates a long default-branch value (text/longtext/json/media)', () => {
    const long = 'x'.repeat(100);
    expect(formatPublicValue(meta('longtext'), long)).toBe(`${'x'.repeat(80)}…`);
    expect(formatPublicValue(meta('text'), 'short')).toBe('short');
  });

  it("formats sensibly without meta, from the value's own runtime type", () => {
    expect(formatPublicValue(undefined, true)).toBe('✓');
    expect(formatPublicValue(undefined, 42)).toBe('42');
    expect(formatPublicValue(undefined, 'hello')).toBe('hello');
  });
});

describe('buildRecordHref', () => {
  it('returns null for a blank template', () => {
    expect(buildRecordHref('', { slug: 's', uuid: 'u' })).toBeNull();
    expect(buildRecordHref('   ', { slug: 's', uuid: 'u' })).toBeNull();
  });

  it('fills {slug} and {uuid}', () => {
    expect(buildRecordHref('/things/{slug}', { slug: 'hello', uuid: 'u1' })).toBe('/things/hello');
    expect(buildRecordHref('/things/{uuid}', { slug: 'hello', uuid: 'u1' })).toBe('/things/u1');
    expect(buildRecordHref('/{slug}/{uuid}', { slug: 'a', uuid: 'b' })).toBe('/a/b');
  });

  it('returns null when the template needs a slug the record does not have', () => {
    expect(buildRecordHref('/things/{slug}', { slug: null, uuid: 'u1' })).toBeNull();
  });

  it('still resolves {uuid} when there is no slug and the template does not need one', () => {
    expect(buildRecordHref('/things/{uuid}', { slug: null, uuid: 'u1' })).toBe('/things/u1');
  });
});
