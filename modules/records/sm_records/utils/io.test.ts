import { describe, expect, it } from 'vitest';

import { importOptionsSummary } from './io';
import type { FieldDef } from './types';

/** A passthrough translator resolves every call to its English default —
 *  the same style `changeLabels.test.ts` uses — plus `{var}` interpolation,
 *  since `importOptionsSummary` builds its "match by" fragment from one. */
function fakeT(_key: string, opts: { defaultValue: string } & Record<string, unknown>): string {
  return opts.defaultValue.replace(/\{(\w+)\}/g, (_match, name) => String(opts[name] ?? ''));
}

function field(overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key: 'email',
    type: 'text',
    label: 'Email',
    required: false,
    unique: true,
    indexed: true,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...overrides,
  };
}

describe('importOptionsSummary', () => {
  it('reads as "mode · match by <label> · force" for the upsert/uuid/off default', () => {
    expect(importOptionsSummary(fakeT, { mode: 'upsert', matchBy: 'uuid', force: false }, [])).toBe(
      'Create or update (upsert) · match by Record ID (uuid) · overwrite unversioned rows: off',
    );
  });

  it('names "Create only" and "Update only" for the other two modes', () => {
    expect(
      importOptionsSummary(fakeT, { mode: 'create', matchBy: 'uuid', force: false }, []),
    ).toContain('Create only ·');
    expect(
      importOptionsSummary(fakeT, { mode: 'update', matchBy: 'uuid', force: false }, []),
    ).toContain('Update only ·');
  });

  it('says "Slug" rather than the raw wire value "slug" (R23)', () => {
    expect(
      importOptionsSummary(fakeT, { mode: 'upsert', matchBy: 'slug', force: false }, []),
    ).toContain('match by Slug');
  });

  it('resolves a match_by that names a unique field to "<label> (<key>)"', () => {
    expect(
      importOptionsSummary(fakeT, { mode: 'upsert', matchBy: 'email', force: false }, [field()]),
    ).toContain('match by Email (email)');
  });

  it('falls back to the raw key if the field is not found (a stale option value)', () => {
    expect(
      importOptionsSummary(fakeT, { mode: 'upsert', matchBy: 'gone', force: false }, [field()]),
    ).toContain('match by gone');
  });

  it('says "on" once force is turned on', () => {
    expect(
      importOptionsSummary(fakeT, { mode: 'upsert', matchBy: 'uuid', force: true }, []),
    ).toContain('overwrite unversioned rows: on');
  });

  it('passes the summary_match_by key and label through to the translator', () => {
    const calls: unknown[][] = [];
    const recordingT = (...args: unknown[]) => {
      calls.push(args);
      return fakeT(args[0] as string, args[1] as { defaultValue: string });
    };
    importOptionsSummary(recordingT, { mode: 'upsert', matchBy: 'uuid', force: false }, []);
    expect(calls).toContainEqual([
      'records.io.summary_match_by',
      { label: 'Record ID (uuid)', defaultValue: 'match by {label}' },
    ]);
  });
});
