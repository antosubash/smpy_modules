import { describe, expect, it } from 'vitest';

import { OFFLINE_STATUS } from './api-net';
import {
  DEFAULT_MAX_IMPORT_BYTES,
  formatImportLimit,
  importApplyBlockedReason,
  importFileTooLarge,
  importOptionsSummary,
  importRecords,
} from './io';
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

describe('the import size guard — R9/M13', () => {
  it('refuses a file over the limit and passes everything under it', () => {
    expect(importFileTooLarge(DEFAULT_MAX_IMPORT_BYTES + 1, DEFAULT_MAX_IMPORT_BYTES)).toBe(true);
    expect(importFileTooLarge(DEFAULT_MAX_IMPORT_BYTES, DEFAULT_MAX_IMPORT_BYTES)).toBe(false);
    expect(importFileTooLarge(10, DEFAULT_MAX_IMPORT_BYTES)).toBe(false);
  });

  it('states the default the settings module ships (pinned in tests/test_reserved_keys_sync.py)', () => {
    expect(DEFAULT_MAX_IMPORT_BYTES).toBe(52428800);
    expect(formatImportLimit(DEFAULT_MAX_IMPORT_BYTES)).toBe('50 MB');
    expect(formatImportLimit(1572864)).toBe('1.5 MB');
  });
});

describe("importRecords shares api.ts's connection handling — R9", () => {
  const file = new File(['[]'], 'rows.json', { type: 'application/json' });

  it("turns a rejected fetch into the module's offline ApiError, not a raw TypeError", async () => {
    const original = globalThis.fetch;
    globalThis.fetch = (() => Promise.reject(new TypeError('Failed to fetch'))) as typeof fetch;
    try {
      await expect(importRecords('book', file)).rejects.toMatchObject({
        name: 'ApiError',
        status: OFFLINE_STATUS,
      });
    } finally {
      globalThis.fetch = original;
    }
  });

  it('answers a 401 with the session-expired message instead of "Import failed (401)"', async () => {
    const original = globalThis.fetch;
    globalThis.fetch = (() =>
      Promise.resolve(
        new Response('{"detail":"Not authenticated"}', { status: 401 }),
      )) as typeof fetch;
    try {
      await expect(importRecords('book', file)).rejects.toMatchObject({
        name: 'ApiError',
        status: 401,
        message: expect.stringContaining('session has expired'),
      });
    } finally {
      globalThis.fetch = original;
    }
  });
});

// U3: one bad row must not silently remove Apply — it must say why the
// button is blocked (or not block it at all, once `on_error: skip` is
// chosen).
describe('importApplyBlockedReason', () => {
  function report(overrides: Partial<{ dry_run: boolean; failed: number; total: number }> = {}) {
    return { dry_run: true, failed: 0, total: 3, ...overrides };
  }

  it('is null for a clean dry run', () => {
    expect(importApplyBlockedReason(fakeT, report({ failed: 0 }), 'abort')).toBeNull();
  });

  it('is null once the report is no longer a dry run — that write already happened', () => {
    expect(
      importApplyBlockedReason(fakeT, report({ dry_run: false, failed: 1 }), 'abort'),
    ).toBeNull();
  });

  it('names the failed/total counts and the skip escape hatch when on_error is abort', () => {
    const reason = importApplyBlockedReason(fakeT, report({ failed: 1, total: 3 }), 'abort');
    expect(reason).toContain('1 of 3');
    expect(reason).toContain('Skip it and write the rest');
  });

  it('is null once the operator has switched to on_error: skip — Apply can run', () => {
    expect(importApplyBlockedReason(fakeT, report({ failed: 1, total: 3 }), 'skip')).toBeNull();
  });
});
