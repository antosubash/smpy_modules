// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { act, mount, press, settle } from '../test-dom';
import type { RecordRead, TypeRead } from '../utils/types';

const updated = vi.fn();

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children }: { children?: unknown }) => children,
  router: { visit: vi.fn(), reload: vi.fn(), on: () => () => {} },
}));
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }) }));
vi.mock('../utils/api-records', () => ({
  updateRecord: (...args: unknown[]) => {
    updated(...(args as []));
    return Promise.resolve(record());
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
