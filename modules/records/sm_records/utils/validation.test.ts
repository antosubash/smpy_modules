import { describe, expect, it } from 'vitest';

import type { FieldDef } from './types';
import { buildValidator, type Translate } from './validation';

/** Returns the key, so a test asserts on the message's identity rather than
 *  on English copy that a translator is free to rewrite. */
const t: Translate = (key) => key;

function field(type: string, overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key: 'f',
    type,
    label: 'F',
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...overrides,
  };
}

function check(def: FieldDef, value: unknown): string | undefined {
  return buildValidator(t, [def])({ [def.key]: value }).f;
}

describe('required', () => {
  it('flags an empty required field and leaves an empty optional alone', () => {
    expect(check(field('text', { required: true }), '')).toBe('records.validation.required');
    expect(check(field('text'), '')).toBeUndefined();
    expect(check(field('multiselect', { required: true }), [])).toBe('records.validation.required');
  });

  it('returns an empty object when every field passes', () => {
    expect(buildValidator(t, [field('text')])({ f: 'ok' })).toEqual({});
  });
});

describe('text constraints', () => {
  it('enforces min_length, max_length and pattern', () => {
    expect(check(field('text', { constraints: { min_length: 3 } }), 'ab')).toBe(
      'records.validation.min_length',
    );
    expect(check(field('text', { constraints: { max_length: 2 } }), 'abc')).toBe(
      'records.validation.max_length',
    );
    expect(check(field('text', { constraints: { pattern: '^[A-Z]' } }), 'abc')).toBe(
      'records.validation.pattern',
    );
    expect(check(field('text', { constraints: { pattern: '^[A-Z]' } }), 'Abc')).toBeUndefined();
  });

  it('defers a pattern JS cannot compile to the server', () => {
    expect(check(field('text', { constraints: { pattern: '(?<' } }), 'abc')).toBeUndefined();
  });
});

describe('email and url', () => {
  it('accepts a plausible address and rejects a typo', () => {
    expect(check(field('email'), 'a@b.co')).toBeUndefined();
    expect(check(field('email'), 'a@b')).toBe('records.validation.email');
  });

  it('requires http(s) with a host', () => {
    expect(check(field('url'), 'https://example.com/x')).toBeUndefined();
    expect(check(field('url'), 'ftp://example.com')).toBe('records.validation.url');
    expect(check(field('url'), 'example.com')).toBe('records.validation.url');
  });
});

describe('media', () => {
  it('caps the stored id or URL at 500 characters', () => {
    expect(check(field('media'), 'x'.repeat(500))).toBeUndefined();
    expect(check(field('media'), 'x'.repeat(501))).toBe('records.validation.max_length');
  });
});

describe('number', () => {
  it('passes five decimals and fails six', () => {
    expect(check(field('number'), '1.12345')).toBeUndefined();
    expect(check(field('number'), '1.123456')).toBe('records.validation.decimals');
  });

  it('rejects text that is not a number at all', () => {
    expect(check(field('number'), '1,5')).toBe('records.validation.not_a_number');
  });

  it('enforces min and max', () => {
    expect(check(field('number', { constraints: { min: 0 } }), '-1')).toBe(
      'records.validation.min',
    );
    expect(check(field('number', { constraints: { max: 10 } }), '10.5')).toBe(
      'records.validation.max',
    );
  });

  it('caps the digits left of the point at what Numeric(19, 5) holds', () => {
    expect(check(field('number'), '12345678901234')).toBeUndefined();
    expect(check(field('number'), '123456789012345')).toBe('records.validation.int_digits');
  });
});

describe('integer', () => {
  it('requires a whole number', () => {
    expect(check(field('integer'), '7')).toBeUndefined();
    expect(check(field('integer'), '7.0')).toBe('records.validation.not_an_integer');
  });

  it('shares the numeric range constraints', () => {
    expect(check(field('integer', { constraints: { max: 5 } }), '6')).toBe(
      'records.validation.max',
    );
  });

  it('caps at the same 14 digits as number (F8)', () => {
    expect(check(field('integer'), '1'.repeat(14))).toBeUndefined();
    expect(check(field('integer'), '1'.repeat(15))).toBe('records.validation.int_digits');
  });
});

describe('boolean, date and datetime', () => {
  it('accepts a real boolean only', () => {
    expect(check(field('boolean'), true)).toBeUndefined();
    expect(check(field('boolean'), 'yes')).toBe('records.validation.boolean');
  });

  it('accepts YYYY-MM-DD only', () => {
    expect(check(field('date'), '2026-09-19')).toBeUndefined();
    expect(check(field('date'), '19/09/2026')).toBe('records.validation.date');
  });

  it('accepts what a datetime-local input produces', () => {
    expect(check(field('datetime'), '2026-09-19T10:30')).toBeUndefined();
    expect(check(field('datetime'), 'tomorrow')).toBe('records.validation.datetime');
  });
});

describe('select and multiselect', () => {
  const options = {
    choices: [
      { value: 'book', label: 'Book' },
      { value: 'dvd', label: 'DVD' },
    ],
  };

  it('requires the value to be one of the configured choices', () => {
    expect(check(field('select', { options }), 'book')).toBeUndefined();
    expect(check(field('select', { options }), 'vhs')).toBe('records.validation.choice');
  });

  it('requires a distinct list of known choices', () => {
    expect(check(field('multiselect', { options }), ['book', 'dvd'])).toBeUndefined();
    expect(check(field('multiselect', { options }), ['book', 'book'])).toBe(
      'records.validation.duplicate_choice',
    );
    expect(check(field('multiselect', { options }), ['vhs'])).toBe('records.validation.choice');
  });
});

describe('json', () => {
  it('requires an object or an array', () => {
    expect(check(field('json'), '{"a": 1}')).toBeUndefined();
    expect(check(field('json'), '[1, 2]')).toBeUndefined();
    expect(check(field('json'), '"scalar"')).toBe('records.validation.json_shape');
    expect(check(field('json'), '{oops')).toBe('records.validation.json');
  });
});

describe('relation', () => {
  const single = field('relation', { options: { target_type: 'person', many: false } });
  const multi = field('relation', { options: { target_type: 'person', many: true } });
  const ref = { type: 'person', uuid: 'a'.repeat(32) };

  it('requires {type, uuid} with a 32-hex uuid', () => {
    expect(check(single, ref)).toBeUndefined();
    expect(check(single, { type: 'person', uuid: 'short' })).toBe('records.validation.relation');
    expect(check(single, { uuid: ref.uuid })).toBe('records.validation.relation');
  });

  it('checks every entry of a to-many field', () => {
    expect(check(multi, [ref])).toBeUndefined();
    expect(check(multi, [ref, { type: 'person', uuid: 'zz' }])).toBe('records.validation.relation');
  });
});

describe('an unknown field type', () => {
  it('is left to the server rather than blocking the save', () => {
    expect(check(field('geo_point'), { lat: 1 })).toBeUndefined();
  });
});

describe('interpolation', () => {
  it('passes the bound value to the translator', () => {
    const interpolating: Translate = (_key, options) =>
      String(options.defaultValue).replace('{{min}}', String(options.min));
    const validator = buildValidator(interpolating, [
      field('text', { constraints: { min_length: 3 } }),
    ]);
    expect(validator({ f: 'ab' })).toEqual({ f: 'Must be at least 3 characters' });
  });
});
