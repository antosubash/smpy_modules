// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount, setValue, settle } from '../test-dom';
import type { FieldDef, RecordListPage, RecordRead, TypeRead } from '../utils/types';

/**
 * A link carrying several `filter=` / `sort=` terms — the grammar repeats
 * both and ANDs the filters, so a hand-written or shared link can hold them
 * even though the filter bar writes one. Review 4 (code F1): a column change
 * rewrote the URL client-side from the first term only while the rows (and
 * "Empty trash"'s count) still answered both, and "Empty trash" then purged
 * the broader set.
 */

let pageUrl = '/admin/records/book';
const get = vi.fn();
const replace = vi.fn();

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
  usePage: () => ({ url: pageUrl, props: { errors: {}, auth: { permissions: ['records.edit'] } } }),
  router: { get, replace, reload: vi.fn(), visit: vi.fn() },
}));
vi.mock('../components/RecordIoMenu', () => ({ RecordIoMenu: () => null }));
vi.mock('../components/RecordsToaster', () => ({ RecordsToaster: () => null }));

const RecordList = (await import('../pages/RecordList')).default;

function field(key: string, overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key,
    type: 'text',
    label: key[0].toUpperCase() + key.slice(1),
    required: false,
    unique: false,
    indexed: true,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...overrides,
  };
}

const type = {
  key: 'book',
  label: 'Book',
  label_plural: 'Books',
  fields: [field('price', { type: 'number' }), field('author'), field('blurb', { indexed: false })],
  display_field: null,
  is_public: false,
  translatable: false,
} as unknown as TypeRead;

function records(overrides: Partial<RecordListPage> = {}): RecordListPage {
  const item = (uuid: string) =>
    ({
      uuid,
      type_key: 'book',
      status: 'draft',
      locale: 'en',
      display_title: `Book ${uuid}`,
      position: 0,
      published_at: null,
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-01T00:00:00+00:00',
      is_deleted: true,
      data: { price: '1', author: 'A', blurb: 'B' },
    }) as unknown as RecordRead;
  return {
    items: [item('r1'), item('r2')],
    total: 7,
    total_capped: false,
    page: 1,
    page_size: 25,
    next_cursor: null,
    ...overrides,
  };
}

const TERMS = ['author:eq:A', 'price:gte:5'];

async function toggleBlurb(view: Awaited<ReturnType<typeof mount>>): Promise<URL> {
  await click(view.find('[data-testid="records-columns-button"]'));
  await click(document.body.querySelector('#records-column-toggle-blurb'));
  return new URL(String(replace.mock.calls.at(-1)?.[0].url), 'http://x');
}

beforeEach(() => {
  get.mockClear();
  replace.mockClear();
  window.localStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  document.body.innerHTML = '';
});

describe('RecordList — a link with repeated filter/sort terms', () => {
  it('a column change keeps both filters, and "Empty trash" then sends both', async () => {
    pageUrl = '/admin/records/book?trashed=true&filter=author:eq:A&filter=price:gte:5&columns=price';
    const view = await mount(<RecordList type={type} records={records()} />);
    const url = await toggleBlurb(view);
    expect(url.searchParams.getAll('filter')).toEqual(TERMS);
    expect(url.searchParams.get('trashed')).toBe('true');
    expect(url.searchParams.get('columns')).toBe('price,blurb');
    await view.unmount();

    // `router.replace` keeps the props: the page renders again from the
    // rewritten URL with the same rows — and "Empty trash" reads it.
    pageUrl = `${url.pathname}${url.search}`;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ purged: 7, filtered: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const again = await mount(<RecordList type={type} records={records()} />);
    await click(again.find('[data-testid="records-empty-trash"]'));
    await setValue(
      document.body.querySelector('#records-empty-trash-confirm') as HTMLInputElement,
      '7',
    );
    await click(document.body.querySelector('[data-slot="alert-dialog-action"]'));
    await settle();
    expect(fetchMock).toHaveBeenCalledOnce();
    const sent = new URL(String(fetchMock.mock.calls[0][0]), 'http://x');
    expect(sent.pathname).toMatch(/\/types\/book\/records\/trash\/empty$/);
    expect(sent.searchParams.getAll('filter')).toEqual(TERMS);
    await again.unmount();
  });

  it('a column change on a cursor page keeps every sort the cursor was signed with', async () => {
    pageUrl = '/admin/records/book?after=CUR&sort=author&sort=-price&columns=price,author';
    const cursor = records({ page: null, total_capped: true, next_cursor: 'N' });
    const view = await mount(<RecordList type={type} records={cursor} />);
    const url = await toggleBlurb(view);
    expect(url.searchParams.getAll('sort')).toEqual(['author', '-price']);
    expect(url.searchParams.get('after')).toBe('CUR');
    await view.unmount();
  });

  it('a cursor step carries every filter and sort term', async () => {
    pageUrl = '/admin/records/book?after=CUR&filter=author:eq:A&filter=price:gte:5&sort=author&sort=-price';
    const cursor = records({ page: null, total_capped: true, next_cursor: 'N' });
    const view = await mount(<RecordList type={type} records={cursor} />);
    await click(view.button('Next page'));
    const url = new URL(String(get.mock.calls.at(-1)?.[0]), 'http://x');
    expect(url.searchParams.get('after')).toBe('N');
    expect(url.searchParams.getAll('filter')).toEqual(TERMS);
    expect(url.searchParams.getAll('sort')).toEqual(['author', '-price']);
    await view.unmount();
  });
});
