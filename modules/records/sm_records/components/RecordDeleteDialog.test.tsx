import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { ReferrerRead } from '../utils/types';
import { DialogDescription, DialogDetails } from './RecordDeleteDialog';

/** A minimal stand-in for `useT()`'s `t`: applies `{name}` interpolation and
 *  picks `defaultValue_other` over `defaultValue` for a `count` other than
 *  one — just enough of i18next's contract for `DialogBody`'s own text. */
function fakeT(key: string, opts?: Record<string, unknown>): string {
  const count = typeof opts?.count === 'number' ? opts.count : undefined;
  const template =
    count !== undefined && count !== 1 && typeof opts?.defaultValue_other === 'string'
      ? (opts.defaultValue_other as string)
      : ((opts?.defaultValue as string) ?? key);
  return template.replace(/\{(\w+)\}/g, (_match, name: string) => String(opts?.[name] ?? ''));
}

function referrer(overrides: Partial<ReferrerRead>): ReferrerRead {
  return {
    type_key: 'book',
    type_label: 'Book',
    uuid: 'book-uuid',
    display_title: 'Dune',
    field_key: 'written_by',
    field_label: 'Written By',
    on_delete: 'restrict',
    is_deleted: false,
    ...overrides,
  };
}

/** `description` (a sentence) and `body` (block content), the way
 *  `RecordDeleteDialog` hands both to `ConfirmDialog` (L6) — concatenated
 *  here since these tests only assert on substrings, not on where the split
 *  falls. */
function html(referrers: ReferrerRead[] | null, loading = false, loadError: string | null = null) {
  return renderToStaticMarkup(
    <>
      <DialogDescription t={fakeT} loading={loading} loadError={loadError} />
      <DialogDetails t={fakeT} loading={loading} loadError={loadError} referrers={referrers} />
    </>,
  );
}

describe('RecordDeleteDialog / DialogDescription + DialogDetails', () => {
  it('shows a checking message while the referrer fetch is in flight', () => {
    const out = html(null, true);
    expect(out).toContain('Checking what references this record…');
  });

  it('surfaces the load error in place of the description', () => {
    const out = html(null, false, 'network down');
    expect(out).toContain('network down');
  });

  it('falls back to the plain confirmation when there are no referrers', () => {
    const out = html([]);
    expect(out).toContain('Delete this record?');
    expect(out).not.toContain('block this delete');
  });

  it('falls back to the plain confirmation when every referrer is trashed', () => {
    const out = html([referrer({ is_deleted: true })]);
    expect(out).toContain('Delete this record?');
  });

  it('names a restrict referrer, links it, and explains the delete is blocked', () => {
    const out = html([referrer({ on_delete: 'restrict', uuid: 'book-1', display_title: 'Dune' })]);
    expect(out).toContain('1 record will block this delete');
    expect(out).toContain('Dune');
    expect(out).toContain('href="/admin/records/book/book-1"');
    expect(out).toContain('Detach or change these references before deleting.');
  });

  it('pluralizes the restrict count', () => {
    const out = html([
      referrer({ on_delete: 'restrict', uuid: 'a' }),
      referrer({ on_delete: 'restrict', uuid: 'b' }),
    ]);
    expect(out).toContain('2 records will block this delete');
  });

  it('describes a set_null referrer without blocking', () => {
    const out = html([referrer({ on_delete: 'set_null', uuid: 'order-1' })]);
    expect(out).toContain('1 record will have this reference cleared');
    expect(out).not.toContain('block this delete');
  });

  it('lists a cascade referrer by name', () => {
    const out = html([
      referrer({ on_delete: 'cascade', uuid: 'child-1', display_title: 'Child Record' }),
    ]);
    expect(out).toContain('1 record will be deleted too');
    expect(out).toContain('Child Record');
  });

  it('a restrict referrer takes precedence over set_null/cascade siblings', () => {
    const out = html([
      referrer({ on_delete: 'restrict', uuid: 'r1' }),
      referrer({ on_delete: 'set_null', uuid: 's1' }),
      referrer({ on_delete: 'cascade', uuid: 'c1' }),
    ]);
    expect(out).toContain('block this delete');
    expect(out).not.toContain('reference cleared');
    expect(out).not.toContain('deleted too');
  });
});
