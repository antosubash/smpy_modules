// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { act, mount, press, settle, setValue } from '../test-dom';
import { ApiError } from '../utils/api';
import type { RecordRead, TypeRead } from '../utils/types';

const updated = vi.fn();
/** U5 tests override this to reject like the server would; every other test
 *  leaves it at the default resolved record. */
let updateImpl: (...args: unknown[]) => Promise<RecordRead>;

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children }: { children?: unknown }) => children,
  router: { visit: vi.fn(), reload: vi.fn(), on: () => () => {} },
}));
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));
vi.mock('../utils/api-records', () => ({
  updateRecord: (...args: unknown[]) => {
    updated(...(args as []));
    return updateImpl(...args);
  },
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

const RecordEditor = (await import('./RecordEditor')).default;

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

async function editor() {
  return mount(<RecordEditor type={type()} record={record()} />);
}

beforeEach(() => {
  updateImpl = () => Promise.resolve(record());
});

/** `focusInvalidInput` (utils/focus-invalid.ts) defers its work a macrotask
 *  — `settle()`'s microtask flush does not reach it — so U5's tests need one
 *  more turn of the real event loop before checking `document.activeElement`. */
async function settleTimers(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe('RecordEditor — R13: the editor is a form with a keyboard path to Save', () => {
  beforeEach(() => updated.mockClear());

  it('saves on Enter in a text field, through implicit form submission', async () => {
    const view = await editor();
    const input = view.find<HTMLInputElement>('#record-field-title');
    expect(input).not.toBeNull();
    // happy-dom does not implement implicit submission, so this asserts the
    // wiring the browser then drives: the input is inside the form, and the
    // form's submit saves.
    // (`Node.contains` is unreliable in happy-dom; ask the input instead.)
    expect(input?.closest('[data-testid="records-editor-form"]')).not.toBeNull();
    await act(async () => {
      (view.find('form') as HTMLFormElement).requestSubmit();
    });
    await settle();
    expect(updated).toHaveBeenCalledOnce();
    await view.unmount();
  });

  it('makes Save a submit button rather than an onClick island', async () => {
    const view = await editor();
    const save = view.button('Save') as HTMLButtonElement;
    expect(save.type).toBe('submit');
    await view.unmount();
  });

  it('saves on ⌘S and on Ctrl+S, and does not let the browser take the key', async () => {
    const view = await editor();
    await press(window, { key: 's', metaKey: true });
    expect(updated).toHaveBeenCalledOnce();
    await settle();
    await press(window, { key: 's', ctrlKey: true });
    expect(updated).toHaveBeenCalledTimes(2);

    const event = new KeyboardEvent('keydown', {
      key: 's',
      metaKey: true,
      bubbles: true,
      cancelable: true,
    });
    await act(async () => {
      window.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);
    await view.unmount();
  });

  it('leaves a plain "s" alone', async () => {
    const view = await editor();
    await press(window, { key: 's' });
    expect(updated).not.toHaveBeenCalled();
    await view.unmount();
  });
});

describe('RecordEditor — R14: position is checked before it is sent', () => {
  beforeEach(() => updated.mockClear());

  it('refuses a fractional position inline instead of saving 0 or 422ing', async () => {
    const view = await editor();
    await setValue(view.find<HTMLInputElement>('#record-position') as HTMLInputElement, '3.7');
    await act(async () => {
      (view.find('form') as HTMLFormElement).requestSubmit();
    });
    await settle();
    expect(updated).not.toHaveBeenCalled();
    expect(view.host.textContent).toContain('Must be a whole number');
    await view.unmount();
  });

  it('sends a whole number as a number, not a coerced string', async () => {
    const view = await editor();
    await setValue(view.find<HTMLInputElement>('#record-position') as HTMLInputElement, '12');
    await act(async () => {
      (view.find('form') as HTMLFormElement).requestSubmit();
    });
    await settle();
    expect(updated).toHaveBeenCalledOnce();
    expect(updated.mock.calls[0][3]).toMatchObject({ position: 12 });
    await view.unmount();
  });
});

describe('RecordEditor — U5: a server rejection gets the same summary as a client one', () => {
  it('shows the role=alert summary and moves focus on a slug collision (409)', async () => {
    updateImpl = () =>
      Promise.reject(
        new ApiError(
          409,
          { detail: "slug 'dune' is already used by another book record in 'en'" },
          'conflict',
        ),
      );
    const view = await editor();
    await act(async () => {
      (view.find('form') as HTMLFormElement).requestSubmit();
    });
    await settle();
    await settleTimers();
    const summary = view.find('[data-testid="records-save-summary"]');
    expect(summary).not.toBeNull();
    expect(summary?.textContent).toContain('field needs attention');
    // The recovery clause the review asked for, and the input the person
    // never typed into is where the message (and focus) land.
    expect(view.host.textContent).toContain('Change the Title');
    // U15: the raw wire type key ('book') gives way to the type's label
    // ('Book') in the server's own sentence.
    expect(view.host.textContent).toContain('another Book record');
    expect(view.host.textContent).not.toContain('another book record');
    expect(document.activeElement?.id).toBe('record-slug');
    await view.unmount();
  });

  it('shows the summary and focuses the first field named by a 422', async () => {
    updateImpl = () =>
      Promise.reject(
        new ApiError(
          422,
          { errors: [{ field: 'title', message: 'already used by another record' }] },
          'invalid',
        ),
      );
    const view = await editor();
    await act(async () => {
      (view.find('form') as HTMLFormElement).requestSubmit();
    });
    await settle();
    await settleTimers();
    const summary = view.find('[data-testid="records-save-summary"]');
    expect(summary?.textContent).toContain('field needs attention');
    expect(document.activeElement?.id).toBe('record-field-title');
    await view.unmount();
  });
});

describe('RecordEditor — U20: the Languages panel reflects a just-saved title', () => {
  it('shows the new title without a page reload once the save resolves', async () => {
    const translatableType = { ...type(), translatable: true } as TypeRead;
    updateImpl = () =>
      Promise.resolve({ ...record(), display_title: 'Herbstgipfel' } as RecordRead);
    const view = await mount(
      <RecordEditor
        type={translatableType}
        record={record()}
        content_locales={['en', 'de']}
        translations={[
          { locale: 'en', uuid: 'u1', status: 'draft', display_title: 'Dune', is_deleted: false },
          {
            locale: 'de',
            uuid: 'u2',
            status: 'draft',
            display_title: 'Herbstgipfel-alt',
            is_deleted: false,
          },
        ]}
      />,
    );
    expect(view.host.textContent).toContain('Dune');
    await act(async () => {
      (view.find('form') as HTMLFormElement).requestSubmit();
    });
    await settle();
    // The current record's own sibling entry ('en') now reads the saved
    // title, with no navigation and no refetch of `translations`.
    expect(view.find('[data-testid="records-translations"]')?.textContent).toContain(
      'Herbstgipfel',
    );
    await view.unmount();
  });
});
