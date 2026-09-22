import { describe, expect, it } from 'vitest';

import { bulkActions, emptyTrashDescription } from './bulk-copy';

/** The same stand-in for `useT()`'s `t` that `RecordDeleteDialog.test.tsx`
 *  uses: `{name}` interpolation and the `_one` plural, which is all i18next's
 *  contract these sentences rely on — and which a mounted test cannot show,
 *  since i18next is unconfigured under vitest. */
function fakeT(key: string, opts?: Record<string, unknown>): string {
  const count = typeof opts?.count === 'number' ? opts.count : undefined;
  const template =
    count === 1 && typeof opts?.defaultValue_one === 'string'
      ? (opts.defaultValue_one as string)
      : ((opts?.defaultValue as string) ?? key);
  return template.replace(/\{(\w+)\}/g, (_m, name: string) => String(opts?.[name] ?? ''));
}

describe('bulkActions — the two sets never mix', () => {
  it('offers Trash, Publish and Unpublish on the live list', () => {
    const actions = bulkActions(fakeT, { count: 3, trashed: false });
    expect(actions.map((a) => a.action)).toEqual(['trash', 'publish', 'unpublish']);
  });

  it('offers Restore and Delete permanently in the Trash view', () => {
    const actions = bulkActions(fakeT, { count: 3, trashed: true });
    expect(actions.map((a) => a.action)).toEqual(['restore', 'purge']);
  });

  it('marks exactly the irreversible-looking ones destructive', () => {
    const live = bulkActions(fakeT, { count: 1, trashed: false });
    expect(live.filter((a) => a.destructive).map((a) => a.action)).toEqual(['trash']);
    const trash = bulkActions(fakeT, { count: 1, trashed: true });
    expect(trash.filter((a) => a.destructive).map((a) => a.action)).toEqual(['purge']);
  });

  it('states the count in every confirmation', () => {
    for (const trashed of [false, true]) {
      for (const action of bulkActions(fakeT, { count: 12, trashed })) {
        expect(action.description).toContain('12');
      }
    }
  });

  it('says "this record" rather than "1 records" for a selection of one', () => {
    const [trash] = bulkActions(fakeT, { count: 1, trashed: false });
    expect(trash.description).toContain('this record');
    expect(trash.description).not.toContain('1 records');
  });

  it('says a trash is reversible and a purge is not', () => {
    const [trash] = bulkActions(fakeT, { count: 4, trashed: false });
    expect(trash.description).toContain('restore');
    const purge = bulkActions(fakeT, { count: 4, trashed: true })[1];
    expect(purge.description).toContain('cannot be undone');
  });
});

describe('emptyTrashDescription — what it is actually about to delete', () => {
  it('says "all" with no filter in force', () => {
    const copy = emptyTrashDescription(fakeT, { count: 12, filtered: false });
    expect(copy).toContain('all 12 trashed records');
    expect(copy).not.toContain('filter');
    expect(copy).toContain('cannot be undone');
  });

  it('says "matching this filter" when one is', () => {
    const copy = emptyTrashDescription(fakeT, { count: 12, filtered: true });
    expect(copy).toContain('the 12 trashed records matching this filter');
    expect(copy).not.toContain('all 12');
  });

  it('says "more than" rather than a total nobody counted when the count is capped', () => {
    const copy = emptyTrashDescription(fakeT, { count: 10000, filtered: false, capped: true });
    expect(copy).toContain('more than 10000');
    const filtered = emptyTrashDescription(fakeT, { count: 10000, filtered: true, capped: true });
    expect(filtered).toContain('matching this filter');
    expect(filtered).toContain('more than 10000');
  });

  it('is singular for one record', () => {
    expect(emptyTrashDescription(fakeT, { count: 1, filtered: false })).toContain(
      '1 trashed record permanently',
    );
  });
});
