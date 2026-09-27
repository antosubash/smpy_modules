// @vitest-environment happy-dom
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount, settle } from '../test-dom';
import { ApiError } from '../utils/api';
import { takeDuplicate } from '../utils/duplicate';
import type { RecordRead, TypeRead } from '../utils/types';

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children }: { children?: unknown }) => children,
  router: { visit: vi.fn(), reload: vi.fn(), on: () => () => {} },
}));
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));
vi.mock('../utils/api-records', () => ({
  updateRecord: vi.fn(),
  createRecord: vi.fn(),
  deleteRecord: vi.fn(),
  purgeRecord: vi.fn(),
  restoreRecord: vi.fn(),
  getRecord: vi.fn(),
}));
vi.mock('../utils/api-history', () => ({
  listReferrers: vi.fn(async () => ({ items: [], total: 0 })),
  listRecordRevisions: vi.fn(async () => ({ items: [] })),
}));

const RecordEditor = (await import('../pages/RecordEditor')).default;
const { router } = await import('@inertiajs/react');
const { updateRecord } = await import('../utils/api-records');

function type(): TypeRead {
  return {
    key: 'book',
    label: 'Book',
    label_plural: 'Books',
    description: null,
    icon: null,
    fields: [
      {
        key: 'title',
        type: 'text',
        label: 'Title',
        required: false,
        unique: false,
        indexed: true,
        default: null,
        help: null,
        constraints: {},
        options: {},
      },
      {
        key: 'isbn',
        type: 'text',
        label: 'ISBN',
        required: false,
        unique: true,
        indexed: true,
        default: null,
        help: null,
        constraints: {},
        options: {},
      },
    ],
    display_field: 'title',
    slug_field: null,
    is_public: false,
    show_in_menu: false,
    translatable: false,
    allowed_roles: [],
    version: 3,
    schema_version: 1,
    record_count: 1,
    trashed_record_count: 0,
    invalid_record_count: 0,
    reindex_pending: {},
  } as unknown as TypeRead;
}

function record(): RecordRead {
  return {
    uuid: 'u1',
    type_key: 'book',
    status: 'draft',
    slug: null,
    locale: 'en',
    translation_group: null,
    display_title: 'Dune',
    position: 0,
    version: 3,
    schema_version: 1,
    published_at: null,
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
    is_deleted: false,
    data: { title: 'Dune', isbn: '000-1' },
    invalid: [],
  } as unknown as RecordRead;
}

/**
 * Missing-item: "Duplicate a record" — a "Save as copy" action on
 * `RecordEditor` opening a prefilled new-record form, minus the record's
 * uuid/slug and any field the schema marks `unique` (`utils/duplicate.ts`
 * carries the "why", including why `unique` values specifically cannot
 * survive the copy). Split into its own file — `RecordEditor.test.tsx`'s
 * own suites already sit close to the 300-line cap.
 */
describe('RecordEditor — Missing-item "Save as copy"', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    (router.visit as ReturnType<typeof vi.fn>).mockClear();
  });

  it('is not offered on a brand-new record — there is nothing yet to copy', async () => {
    const view = await mount(<RecordEditor type={type()} record={null} />);
    expect(view.find('[data-testid="records-editor-duplicate"]')).toBeNull();
    await view.unmount();
  });

  it('stashes the current data and navigates to the type’s "new" screen', async () => {
    const view = await mount(<RecordEditor type={type()} record={record()} />);
    await click(view.find('[data-testid="records-editor-duplicate"]'));
    expect(router.visit).toHaveBeenCalledWith('/admin/records/book/new');
    const stashed = takeDuplicate('book');
    // `isbn` is `unique` on this type — dropped, per `withoutUniqueValues`.
    expect(stashed?.data).toEqual({ title: 'Dune' });
    await view.unmount();
  });

  it('prefills a fresh new-record visit from what was stashed, unique fields dropped', async () => {
    const view = await mount(<RecordEditor type={type()} record={record()} />);
    await click(view.find('[data-testid="records-editor-duplicate"]'));
    await view.unmount();

    // The navigation this triggers is `/…/new`, i.e. a second mount with
    // `record={null}` — exactly what that visit renders.
    const fresh = await mount(<RecordEditor type={type()} record={null} />);
    expect(fresh.find<HTMLInputElement>('#record-field-title')?.value).toBe('Dune');
    expect(fresh.find<HTMLInputElement>('#record-field-isbn')?.value ?? '').toBe('');
    await fresh.unmount();
  });
});

/** A 409 on save opens `ConflictPanel`; its "Reload" adopts the server's copy
 *  — the envelope inputs and the form re-sync from it and the panel closes
 *  (`useRecordEditor`'s `reloadFromConflict`). */
describe('RecordEditor — a stale save’s Reload adopts the server copy', () => {
  it('re-syncs the form and the slug from the server record and closes the panel', async () => {
    const server = {
      ...record(),
      version: 4,
      slug: 'dune-2',
      data: { title: 'Dune II', isbn: '000-1' },
    };
    vi.mocked(updateRecord).mockRejectedValueOnce(
      new ApiError(409, { detail: 'stale', current: server } as never, 'stale'),
    );
    const view = await mount(<RecordEditor type={type()} record={record()} />);
    await act(async () => {
      (view.find('form') as HTMLFormElement).requestSubmit();
    });
    await settle();
    expect(view.find('[data-testid="records-conflict-panel"]')).not.toBeNull();
    await click(view.button('Reload'));
    expect(view.find('[data-testid="records-conflict-panel"]')).toBeNull();
    expect(view.find<HTMLInputElement>('#record-field-title')?.value).toBe('Dune II');
    expect(view.find<HTMLInputElement>('#record-slug')?.value).toBe('dune-2');
    await view.unmount();
  });
});
