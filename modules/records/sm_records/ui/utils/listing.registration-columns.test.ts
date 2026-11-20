import { describe, expect, it } from 'vitest';

import { defaultColumnKeys } from './listing';
import type { FieldDef } from './types';

function field(key: string, overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key,
    type: 'text',
    label: key.toUpperCase(),
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

describe('a registration type', () => {
  const fields = [
    field('sm_email', { indexed: true }),
    field('sm_event_id', { indexed: true }),
    field('sm_event_title'),
    field('sm_occurrence_start', { type: 'datetime', indexed: true }),
    field('sm_status', { type: 'select', indexed: true }),
  ];
  const registration = {
    fields,
    display_field: 'sm_name',
    public_submissions: { kind: 'registration' },
  };

  it('lists its registration status, the event title and the date by default, not Draft and an id', () => {
    const keys = defaultColumnKeys(registration, false);
    expect(keys.slice(0, 3)).toEqual(['sm_status', 'sm_event_title', 'sm_occurrence_start']);
    expect(keys).not.toContain('status'); // the generic Draft/Published column
    expect(keys).not.toContain('sm_event_id'); // a raw id
  });

  it('keeps the generic default for any other type', () => {
    const keys = defaultColumnKeys({ fields, display_field: null }, false);
    expect(keys[0]).toBe('status');
  });
});
