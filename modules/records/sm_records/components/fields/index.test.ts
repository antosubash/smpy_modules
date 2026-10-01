import { describe, expect, it } from 'vitest';

import { FIELD_COMPONENTS, getFieldComponent, UnknownField } from './index';

/** The closed field-type set of design §6.1. If a type is added there and
 *  not here, this is what says so. */
const FIELD_TYPES = [
  'text',
  'longtext',
  'number',
  'integer',
  'boolean',
  'date',
  'datetime',
  'select',
  'multiselect',
  'email',
  'url',
  'json',
  'media',
  'relation',
];

describe('the field registry', () => {
  it('covers every field type exactly once', () => {
    expect(Object.keys(FIELD_COMPONENTS).sort()).toEqual([...FIELD_TYPES].sort());
  });

  it('returns a component for each of them', () => {
    for (const type of FIELD_TYPES) {
      expect(typeof getFieldComponent(type)).toBe('function');
    }
  });

  it('falls back to the read-only UnknownField rather than crashing', () => {
    expect(getFieldComponent('geo_point')).toBe(UnknownField);
    expect(getFieldComponent('')).toBe(UnknownField);
    // A key that exists on Object.prototype must not resolve to its method.
    expect(getFieldComponent('constructor')).toBe(UnknownField);
  });
});
