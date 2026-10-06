// @vitest-environment happy-dom
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { mount, settle } from '../test-dom';
import type { RecordRead, TypeRead } from '../utils/types';

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  usePage: () => ({ url: '/admin/records', props: {} }),
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
const { createRecord, updateRecord } = await import('../utils/api-records');

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
    ],
    display_field: 'title',
    slug_field: null,
    is_public: false,
    show_in_menu: false,
    translatable: false,
    allowed_roles: [],
    version: 3,
    schema_version: 1,
    record_count: 0,
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
    data: { title: 'Dune' },
    invalid: [],
  } as unknown as RecordRead;
}

/** A promise the test resolves by hand, so the save stays in flight. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

/** QA (ship round 1): five quick clicks on Save for a new record sent two
 *  POSTs and created two records — `pending` disables the button only once
 *  React re-renders, which several clicks can beat. */
describe('RecordEditor — a save already in flight swallows repeat presses', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.mocked(router.visit).mockClear();
    vi.mocked(createRecord).mockReset();
    vi.mocked(updateRecord).mockReset();
  });

  it('creates the record once however many times the form is submitted', async () => {
    const create = deferred<RecordRead>();
    vi.mocked(createRecord).mockReturnValue(create.promise);
    const view = await mount(<RecordEditor type={type()} record={null} />);
    const form = view.find('form') as HTMLFormElement;
    await act(async () => {
      form.requestSubmit();
      form.requestSubmit();
      form.requestSubmit();
    });
    expect(createRecord).toHaveBeenCalledTimes(1);
    await act(async () => create.resolve({ ...record(), uuid: 'new-1' }));
    await settle();
    // Still guarded while the visit to the new record is under way.
    await act(async () => form.requestSubmit());
    expect(createRecord).toHaveBeenCalledTimes(1);
    expect(router.visit).toHaveBeenCalledTimes(1);
    expect(router.visit).toHaveBeenCalledWith('/admin/records/book/new-1');
    await view.unmount();
  });

  it('sends one update per completed save, and allows the next once it lands', async () => {
    const first = deferred<RecordRead>();
    vi.mocked(updateRecord).mockReturnValueOnce(first.promise);
    vi.mocked(updateRecord).mockResolvedValueOnce({ ...record(), version: 5 });
    const view = await mount(<RecordEditor type={type()} record={record()} />);
    const form = view.find('form') as HTMLFormElement;
    await act(async () => {
      form.requestSubmit();
      form.requestSubmit();
    });
    expect(updateRecord).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve({ ...record(), version: 4 }));
    await settle();
    await act(async () => form.requestSubmit());
    await settle();
    expect(updateRecord).toHaveBeenCalledTimes(2);
    await view.unmount();
  });
});
