// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount } from '../test-dom';
import type { RecordRead, TypeRead } from '../utils/types';

// Split out of RecordEditor.test.tsx for the 300-line cap, the same way
// RecordEditor.duplicate.test.tsx already is — each of these mounts the
// whole page, so the fixtures below are this file's own copy rather than a
// shared import: `pages/` may hold nothing but real Inertia pages, so there
// is nowhere in this module to put one both files could import from.
vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  // PageShell reads the URL to report its heading (ui 0.0.35).
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
    record_count: 1,
    trashed_record_count: 0,
    invalid_record_count: 1,
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
    invalid: [{ field: 'title', message: 'Field required' }],
  } as unknown as RecordRead;
}

describe(
  "RecordEditor — U9: a stored invalid mark reads the same as the type editor's own report",
  () => {
    it('humanizes "Field required" under the affected field, not just in the top notice', async () => {
      const view = await mount(<RecordEditor type={type()} record={record()} />);

      // The top-of-page notice (InvalidNotice) and the field's own error
      // slot are two different renderings of the same `record.invalid`
      // entry — both have to read the humanized text, not pydantic's raw
      // wording.
      const notice = view.find('[data-testid="records-invalid-notice"]');
      expect(notice?.textContent).toContain('no value for it');
      expect(notice?.textContent).not.toContain('Field required');

      const fieldError = view.find('[data-testid="records-field-error-title"]');
      expect(fieldError?.textContent).toBe('required, but this record has no value for it');
      await view.unmount();
    });
  },
);
