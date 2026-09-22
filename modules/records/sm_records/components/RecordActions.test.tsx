// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount, settle } from '../test-dom';
import type { RecordRead } from '../utils/types';

const deleted = vi.fn(async () => undefined);
const purged = vi.fn(async () => undefined);

vi.mock('@inertiajs/react', () => ({
  Link: ({ children }: { children?: unknown }) => children,
  router: { reload: vi.fn(), visit: vi.fn() },
}));
vi.mock('../utils/api-records', () => ({
  deleteRecord: (...args: unknown[]) => deleted(...(args as [])),
  purgeRecord: (...args: unknown[]) => purged(...(args as [])),
  restoreRecord: vi.fn(async () => ({})),
}));
vi.mock('../utils/api-history', () => ({ listReferrers: vi.fn(async () => ({ items: [] })) }));
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));

const { RecordActions } = await import('./RecordActions');

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
    is_deleted: false,
    data: {},
    invalid: [],
    ...overrides,
  } as RecordRead;
}

/** Radix renders the dialog into a portal on `document.body`, so the
 *  confirm button is looked up there rather than inside the mount host —
 *  and by its slot, since the trigger carries the same label. */
function confirmButton(): HTMLElement | null {
  return document.querySelector('[data-slot="alert-dialog-action"]');
}

describe('RecordActions — R4: the unsaved-changes guard is told before we navigate', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    deleted.mockClear();
    purged.mockClear();
  });

  it('calls allowNavigation before onGone on a permanent delete', async () => {
    const calls: string[] = [];
    const view = await mount(
      <RecordActions
        typeKey="book"
        record={record({ is_deleted: true })}
        allowNavigation={() => calls.push('allow')}
        onRestored={() => {}}
        onGone={() => calls.push('gone')}
      />,
    );
    await click(view.button('Delete permanently'));
    await settle();
    await click(confirmButton());
    await settle();
    expect(purged).toHaveBeenCalledOnce();
    // Order matters: `onGone` is an ordinary Inertia visit, and the guard
    // reads `allow` synchronously in its `before` handler.
    expect(calls).toEqual(['allow', 'gone']);
    await view.unmount();
  });

  it('calls allowNavigation before onGone on a soft delete', async () => {
    const calls: string[] = [];
    const view = await mount(
      <RecordActions
        typeKey="book"
        record={record()}
        allowNavigation={() => calls.push('allow')}
        onRestored={() => {}}
        onGone={() => calls.push('gone')}
      />,
    );
    await click(view.button('Delete'));
    await settle();
    await click(confirmButton());
    await settle();
    expect(deleted).toHaveBeenCalledOnce();
    expect(calls).toEqual(['allow', 'gone']);
    await view.unmount();
  });
});
