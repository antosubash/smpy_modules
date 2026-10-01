import { describe, expect, it } from 'vitest';

import type { FieldDef } from './types';
import {
  buildPayload,
  formatDateTime,
  isoToLocalInput,
  localInputToIso,
  parsePosition,
  toApiValue,
  toFormValue,
  toFormValues,
} from './values';

function field(type: string, overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key: overrides.key ?? 'f',
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

/**
 * The `number` contract is the one this module exists to protect: five
 * decimals, carried as a string end to end (design §7.3).
 */
describe('number values stay strings', () => {
  it('keeps the API string verbatim in form state', () => {
    expect(toFormValue(field('number'), '9.99000')).toBe('9.99000');
  });

  it('sends the typed text back without a float round trip', () => {
    // 0.1 + 0.2 territory: parseFloat/String would change these digits.
    expect(toApiValue(field('number'), '12345678901234.12345')).toBe('12345678901234.12345');
    expect(toApiValue(field('number'), ' 0.30000 ')).toBe('0.30000');
  });

  it('treats an empty numeric field as absent, not as zero', () => {
    expect(toApiValue(field('number'), '')).toBeUndefined();
  });
});

describe('integer values', () => {
  it('goes out as a string, like number, not a JS number', () => {
    expect(toApiValue(field('integer'), '42')).toBe('42');
  });

  it('preserves every digit past Number.isSafeInteger', () => {
    // Number("99999999999999999") rounds to 100000000000000000.
    expect(toApiValue(field('integer'), '99999999999999999')).toBe('99999999999999999');
  });

  it('trims surrounding whitespace', () => {
    expect(toApiValue(field('integer'), ' 42 ')).toBe('42');
  });

  it('hands non-integer text through so the server names the problem', () => {
    expect(toApiValue(field('integer'), '1.5')).toBe('1.5');
  });

  it('treats an empty integer field as absent', () => {
    expect(toApiValue(field('integer'), '')).toBeUndefined();
  });
});

describe('datetime never leaves naive', () => {
  it('stamps an offset on whatever datetime-local produced', () => {
    const out = toApiValue(field('datetime'), '2026-09-19T10:30');
    expect(typeof out).toBe('string');
    expect(out as string).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/);
  });

  it('round-trips an offset-carrying value through the local input shape', () => {
    const local = isoToLocalInput(new Date('2026-09-19T10:30:00Z').toISOString());
    expect(local).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/);
    expect(new Date(localInputToIso(local)).toISOString()).toBe('2026-09-19T10:30:00.000Z');
  });

  it('keeps seconds across the round trip instead of dropping them (F4)', () => {
    // Compared as instants (via getTime()), not strings: `localInputToIso`
    // stamps the *test runner's* offset, which isn't necessarily UTC.
    const original = '2024-03-10T12:30:45+00:00';
    const local = isoToLocalInput(original);
    expect(local).toMatch(/:45$/);
    expect(new Date(localInputToIso(local)).getTime()).toBe(new Date(original).getTime());
  });

  it('hands unparseable text back rather than inventing a timestamp', () => {
    expect(localInputToIso('not a date')).toBe('not a date');
  });
});

describe('formatDateTime', () => {
  // The rough edge this exists to close: `published_at`/`updated_at` used to
  // print the raw ISO envelope timestamp (`2026-09-21T06:16:27.404600`) right
  // next to a schema `datetime` field formatted with `Intl.DateTimeFormat` —
  // this is the one function both now go through.
  it('formats an ISO datetime with a locale date and short time, not the raw string', () => {
    const out = formatDateTime('2026-09-21T06:16:27.404600+00:00');
    expect(out).not.toBe('2026-09-21T06:16:27.404600+00:00');
    expect(out).not.toContain('T');
    expect(out).toMatch(/2026/);
  });

  it('hands unparseable text back rather than inventing a display value', () => {
    expect(formatDateTime('not a date')).toBe('not a date');
  });
});

describe('date values', () => {
  it('keeps only the calendar part', () => {
    expect(toFormValue(field('date'), '2026-09-19')).toBe('2026-09-19');
    expect(toApiValue(field('date'), '2026-09-19')).toBe('2026-09-19');
  });
});

describe('boolean keeps "never set" distinct from false', () => {
  it('reads a missing value as null and omits it on the way out', () => {
    expect(toFormValue(field('boolean'), undefined)).toBeNull();
    expect(toApiValue(field('boolean'), null)).toBeUndefined();
    expect(toApiValue(field('boolean'), false)).toBe(false);
  });
});

describe('json values', () => {
  it('edits as pretty text and parses on the way out', () => {
    expect(toFormValue(field('json'), { a: 1 })).toBe('{\n  "a": 1\n}');
    expect(toApiValue(field('json'), '{"a": 1}')).toEqual({ a: 1 });
  });
});

describe('relation values', () => {
  const single = field('relation', { options: { target_type: 'person', many: false } });
  const multi = field('relation', { key: 'm', options: { target_type: 'person', many: true } });
  const ref = { type: 'person', uuid: 'a'.repeat(32) };

  it('carries {type, uuid} for a to-one field', () => {
    expect(toFormValue(single, ref)).toEqual(ref);
    expect(toApiValue(single, ref)).toEqual(ref);
  });

  it('carries a list for a to-many field and drops junk entries', () => {
    expect(toFormValue(multi, [ref, 'nope'])).toEqual([ref]);
    expect(toApiValue(multi, [])).toBeUndefined();
  });
});

describe('datetime keeps what it was given — R2', () => {
  const when = field('datetime', { key: 'when' });
  const stored = '2026-01-15T10:30:00.123456+00:00';

  it('sends the stored microsecond value back verbatim when the input is untouched', () => {
    const inForm = toFormValue(when, stored);
    expect(toApiValue(when, inForm, stored)).toBe(stored);
  });

  it('and buildPayload therefore reads clean instead of silently truncating', () => {
    const fields = [when];
    const original = { when: stored };
    const payload = buildPayload(fields, toFormValues(fields, original), original);
    // Byte for byte what the server holds: before R2 this was
    // "2026-01-15T10:30:00+01:00", the dirty check compared the truncation
    // against itself and said "no unsaved changes", and a save of any other
    // field wrote the lost microseconds through.
    expect(payload.when).toBe(stored);
  });

  it('still re-serialises a value the person actually edited', () => {
    const edited = toApiValue(when, '2026-01-15T11:45:00', stored);
    expect(edited).not.toBe(stored);
    expect(edited as string).toMatch(/^2026-01-15T11:45:00[+-]\d{2}:\d{2}$/);
  });

  it('has nothing to preserve on a create, and stamps the offset as before', () => {
    expect(toApiValue(when, '2026-01-15T11:45:00') as string).toMatch(
      /^2026-01-15T11:45:00[+-]\d{2}:\d{2}$/,
    );
  });
});

describe('buildPayload', () => {
  const fields = [field('text', { key: 'title' }), field('text', { key: 'subtitle' })];

  it('omits an empty optional on a create so the default applies', () => {
    expect(buildPayload(fields, { title: 'Hi', subtitle: '' }, null)).toEqual({ title: 'Hi' });
  });

  it('sends null when the key already existed, so clearing clears', () => {
    const original = { title: 'Hi', subtitle: 'was here' };
    expect(buildPayload(fields, { title: 'Hi', subtitle: '' }, original)).toEqual({
      title: 'Hi',
      subtitle: null,
    });
  });

  it('never re-sends _orphaned, even when the original record carried one (F2)', () => {
    // services/_payload.py refuses the key outright on any write;
    // update_record carries the stored value forward itself.
    const original = { title: 'Hi', subtitle: 'was here', _orphaned: { gone: 1 } };
    expect(buildPayload(fields, { title: 'Hi', subtitle: '' }, original)).toEqual({
      title: 'Hi',
      subtitle: null,
    });
  });
});

describe('toFormValues', () => {
  it('materialises every declared key, even one the payload lacks', () => {
    const fields = [field('text', { key: 'a' }), field('multiselect', { key: 'b' })];
    expect(toFormValues(fields, { a: 'x' })).toEqual({ a: 'x', b: [] });
  });
});

describe("parsePosition — R14: the envelope's one numeric input is checked too", () => {
  it('takes a whole number, signed or not', () => {
    expect(parsePosition('0')).toBe(0);
    expect(parsePosition('42')).toBe(42);
    expect(parsePosition(' 7 ')).toBe(7);
    expect(parsePosition('-3')).toBe(-3);
    expect(parsePosition('+3')).toBe(3);
  });

  it('refuses what `Number(position) || 0` used to swallow', () => {
    // A browser hands back '' for text a number input cannot parse — the
    // case that saved 0 with no message at all.
    expect(parsePosition('')).toBeNull();
    expect(parsePosition('   ')).toBeNull();
    expect(parsePosition('abc')).toBeNull();
    // 1e3 silently saved 1000.
    expect(parsePosition('1e3')).toBeNull();
    // 3.7 went to the server and came back a 422.
    expect(parsePosition('3.7')).toBeNull();
    expect(parsePosition('9007199254740993')).toBeNull();
  });
});
