// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import type { RecordRead } from '../utils/types';

vi.mock('../utils/api-history', () => ({ listReferrers: vi.fn(async () => ({ items: [] })) }));

const { RecordRowAction } = await import('./RecordRowAction');

function record(overrides: Partial<RecordRead> = {}): RecordRead {
  return {
    uuid: 'u1',
    type_key: 'book',
    status: 'draft',
    slug: null,
    locale: 'en',
    translation_group: null,
    display_title: 'Dune',
    position: 0,
    version: 1,
    schema_version: 1,
    published_at: null,
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
    is_deleted: true,
    data: {},
    invalid: [],
    ...overrides,
  } as RecordRead;
}

/** Both confirm buttons render into the same document.body portal (Radix
 *  AlertDialog), so only one dialog is open at a time in practice — grabbed
 *  by slot right after the specific trigger that opened it, same pattern as
 *  `RecordActions.test.tsx`. */
function confirmButton(): HTMLElement | null {
  return document.querySelector('[data-slot="alert-dialog-action"]');
}

describe('RecordRowAction — U4: the Trash view can release a record for good', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('offers Restore and Delete permanently on a trashed row, and only calls onPurge on confirm', async () => {
    const onDelete = vi.fn(async () => undefined);
    const onRestore = vi.fn(async () => undefined);
    const onPurge = vi.fn(async () => undefined);
    const view = await mount(
      <RecordRowAction
        typeKey="book"
        record={record()}
        title={record().display_title}
        trashed
        onDelete={onDelete}
        onRestore={onRestore}
        onPurge={onPurge}
      />,
    );
    expect(view.button('Restore')).toBeDefined();
    expect(view.button('Delete permanently')).toBeDefined();

    await click(view.button('Delete permanently'));
    await click(confirmButton());
    expect(onPurge).toHaveBeenCalledWith(record());
    expect(onRestore).not.toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('does not offer Delete permanently on a live row', async () => {
    const view = await mount(
      <RecordRowAction
        typeKey="book"
        record={record({ is_deleted: false })}
        title={record().display_title}
        trashed={false}
        onDelete={async () => undefined}
        onRestore={async () => undefined}
        onPurge={async () => undefined}
      />,
    );
    expect(view.button('Delete permanently')).toBeUndefined();
    expect(view.button('Delete')).toBeDefined();
    await view.unmount();
  });
});

describe('RecordRowAction — U27: every row action names the record it acts on', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('carries the record title in aria-label on a live row, not just "Delete"', async () => {
    const view = await mount(
      <RecordRowAction
        typeKey="book"
        record={record({ is_deleted: false, display_title: 'Dune' })}
        title="Dune"
        trashed={false}
        onDelete={async () => undefined}
        onRestore={async () => undefined}
        onPurge={async () => undefined}
      />,
    );
    const btn = view.find<HTMLButtonElement>('button');
    // A record-specific name rather than the plain "Delete" every other row
    // would share. The catalogue is loaded under vitest (`tests/vitest-i18n.ts`),
    // so this also proves the title is interpolated.
    expect(btn?.getAttribute('aria-label')).toBe('Delete Dune');
    await view.unmount();
  });

  it('carries a distinct, record-naming aria-label on Restore and Delete permanently', async () => {
    const view = await mount(
      <RecordRowAction
        typeKey="book"
        record={record({ display_title: 'Dune' })}
        title="Dune"
        trashed
        onDelete={async () => undefined}
        onRestore={async () => undefined}
        onPurge={async () => undefined}
      />,
    );
    const buttons = view.all<HTMLButtonElement>('button');
    const labels = buttons.map((btn) => btn.getAttribute('aria-label'));
    expect(labels).toEqual(['Restore Dune', 'Delete Dune permanently']);
    await view.unmount();
  });
});
