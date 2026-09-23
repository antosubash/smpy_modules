// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount } from '../test-dom';
import type { RecordRead, TypeRead } from '../utils/types';

// Split out of RecordEditor.test.tsx for the 300-line cap, the same way
// RecordEditor.duplicate.test.tsx and RecordEditor.invalid.test.tsx already
// are — each of these mounts the whole page, so the fixtures below are this
// file's own copy rather than a shared import: `pages/` may hold nothing but
// real Inertia pages, so there is nowhere in this module to put one both
// files could import from.
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

function type(): TypeRead {
  return {
    key: 'book',
    label: 'Book',
    label_plural: 'Books',
    description: null,
    icon: null,
    fields: [],
    display_field: null,
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
    data: {},
    invalid: [],
  } as unknown as RecordRead;
}

describe('RecordEditor — the tenant badge (tenancy design §J)', () => {
  it('shows nothing on a single-tenant host', async () => {
    const view = await mount(
      <RecordEditor type={type()} record={record()} tenant="default" tenancy_mode="single" />,
    );
    expect(view.find('[data-testid="records-tenant-badge"]')).toBeNull();
    await view.unmount();
  });

  it('shows nothing when tenancy_mode is absent — an older fixture or a screen tenancy has not reached', async () => {
    const view = await mount(<RecordEditor type={type()} record={record()} />);
    expect(view.find('[data-testid="records-tenant-badge"]')).toBeNull();
    await view.unmount();
  });

  it('shows the working tenant once tenancy_mode is multi, on the new-record screen too', async () => {
    const view = await mount(
      <RecordEditor type={type()} record={null} tenant="acme" tenancy_mode="multi" />,
    );
    expect(view.find('[data-testid="records-tenant-badge"]')).not.toBeNull();
    await view.unmount();
  });
});
