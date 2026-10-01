// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import type { RecordListPage, RecordRead, TypeRead } from '../utils/types';

// The page reads its URL and `list_errors` from `usePage()`; both change between
// renders here, the way a cursor step changes them.
let pageUrl = '/admin/records/book?sort=name&after=CURSOR-1';
let pageErrors: Record<string, string> = {};
const get = vi.fn();

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
  usePage: () => ({
    url: pageUrl,
    props: { list_errors: pageErrors, auth: { permissions: ['records.edit'] } },
  }),
  router: { get: (...args: unknown[]) => get(...args), reload: vi.fn(), visit: vi.fn() },
}));
vi.mock('../components/RecordIoMenu', () => ({ RecordIoMenu: () => null }));
vi.mock('../components/RecordsToaster', () => ({ RecordsToaster: () => null }));

const RecordList = (await import('../pages/RecordList')).default;

const type = {
  key: 'book',
  label: 'Book',
  label_plural: 'Books',
  fields: [],
  display_field: null,
  is_public: false,
} as unknown as TypeRead;

function record(uuid: string): RecordRead {
  return {
    uuid,
    type_key: 'book',
    status: 'draft',
    slug: null,
    locale: 'en',
    translation_group: null,
    display_title: `Book ${uuid}`,
    position: 0,
    version: 1,
    schema_version: 1,
    published_at: null,
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
    is_deleted: false,
    data: {},
    invalid: [],
  } as unknown as RecordRead;
}

function cursorPage(prefix: string, next: string | null, count = 25): RecordListPage {
  return {
    items: Array.from({ length: count }, (_, i) => record(`${prefix}${i}`)),
    total: 32,
    total_capped: true,
    page: null,
    page_size: 25,
    next_cursor: next,
  };
}

/** The URL of the last `router.get` — the page passes the whole URL, since a
 *  `data` object cannot repeat a key — and its params. */
const lastUrl = () => new URL(String(get.mock.calls.at(-1)?.[0]), 'http://x');
const lastParams = () => Object.fromEntries(lastUrl().searchParams);

describe('RecordList — paging past the cap by cursor', () => {
  beforeEach(() => {
    get.mockClear();
    pageUrl = '/admin/records/book?sort=name&after=CURSOR-1';
    pageErrors = {};
  });

  it('Next page writes ?after=next_cursor with the sort and no page number', async () => {
    const view = await mount(<RecordList type={type} records={cursorPage('a', 'CURSOR-2')} />);
    expect(view.find('[data-testid="records-cursor-pager"]')).not.toBeNull();
    await click(view.button('Next page'));
    expect(lastUrl().pathname).toBe('/admin/records/book');
    expect(lastParams()).toEqual({ after: 'CURSOR-2', sort: 'name' });
    await view.unmount();
  });

  it('First page drops the cursor and keeps the sort', async () => {
    const view = await mount(<RecordList type={type} records={cursorPage('a', 'CURSOR-2')} />);
    await click(view.button('First page'));
    expect(lastParams()).toEqual({ sort: 'name' });
    await view.unmount();
  });

  it('announces the count without a page number', async () => {
    const view = await mount(<RecordList type={type} records={cursorPage('a', 'CURSOR-2')} />);
    // No catalog is configured here, so `{count}` is not interpolated; the
    // sentence is what says which one was chosen.
    const status = view.find('[data-testid="records-list-status"]')?.textContent;
    expect(status).toMatch(/continuing in the same order$/);
    expect(status).not.toMatch(/page/);
    await view.unmount();
  });

  it('a cursor step resets the selection and the bulk toolbar, as a page change does', async () => {
    const view = await mount(<RecordList type={type} records={cursorPage('a', 'CURSOR-2')} />);
    await click(view.find('[data-testid="records-select-row"]'));
    expect(view.find('[data-testid="records-bulk-toolbar"]')).not.toBeNull();

    pageUrl = '/admin/records/book?sort=name&after=CURSOR-2';
    await view.render(<RecordList type={type} records={cursorPage('b', 'CURSOR-3')} />);
    expect(view.find('[data-testid="records-bulk-toolbar"]')).toBeNull();
    const boxes = view.all('[data-testid="records-select-row"]');
    expect(boxes.every((box) => box.getAttribute('aria-checked') !== 'true')).toBe(true);
    // The part only a reset proves — `visible()` alone would hide a stale
    // tick on the page above: Back to the first page shows nothing ticked.
    pageUrl = '/admin/records/book?sort=name&after=CURSOR-1';
    await view.render(<RecordList type={type} records={cursorPage('a', 'CURSOR-2')} />);
    expect(view.find('[data-testid="records-bulk-toolbar"]')).toBeNull();
    await view.unmount();
  });

  it('an empty page past the last row says so, and never "No records yet"', async () => {
    const view = await mount(<RecordList type={type} records={cursorPage('a', null, 0)} />);
    expect(view.find('[data-testid="records-empty-cursor"]')?.textContent).toBe(
      'There are no more records after the previous page.',
    );
    expect(view.host.textContent).not.toContain('No records yet');
    // The filter bar stays: the type is not empty, only this page is.
    expect(view.find('[data-testid="records-filter-bar"]')).not.toBeNull();
    // Review 4, ux F5: nothing continues from here, so the footer says
    // nothing about continuing and leaves "First page" to the box.
    expect(view.find('[data-testid="records-page-cursor"]')).toBeNull();
    expect(view.button('Next page')).toBeUndefined();
    expect(view.all('button').filter((b) => b.textContent === 'First page')).toHaveLength(1);
    expect(view.find('#records-page-size')).not.toBeNull();
    expect(view.find('[data-testid="records-list-status"]')?.textContent).toBe(
      'No more records after the previous page',
    );
    await view.unmount();
  });

  it('a refused link keeps the footer quiet too: no "continues", one First page', async () => {
    pageUrl = '/admin/records/book?sort=name&after=TAMPERED';
    pageErrors = { filter: 'bad_cursor' };
    const view = await mount(<RecordList type={type} records={cursorPage('a', null, 0)} />);
    expect(view.find('[data-testid="records-page-cursor"]')).toBeNull();
    expect(view.all('button').filter((b) => b.textContent === 'First page')).toHaveLength(1);
    const status = view.find('[data-testid="records-list-status"]')?.textContent;
    expect(status).toMatch(/^This link can't continue the list/);
    expect(status).not.toMatch(/continuing/);
    await view.unmount();
  });

  it('a refused cursor is the notice, and the empty box offers the first page', async () => {
    pageUrl = '/admin/records/book?sort=name&filter=name%3Aeq%3Ax&after=TAMPERED';
    pageErrors = { filter: 'bad_cursor' };
    const view = await mount(<RecordList type={type} records={cursorPage('a', null, 0)} />);
    expect(view.find('[data-testid="records-filter-error"]')?.textContent).toMatch(
      /^This link can't continue the list/,
    );
    expect(view.find('[data-testid="records-empty-cursor"]')?.textContent).toBe(
      'Nothing to show — this link could not continue the list.',
    );
    // The box's button goes to page 1 and keeps the filter, which was fine.
    const box = view.find('[data-testid="records-empty-state"]');
    await click(box?.querySelector('button'));
    expect(lastParams()).toEqual({ sort: 'name', filter: 'name:eq:x' });
    await view.unmount();
  });

  it('a refused sort or filter on a cursor link is not "no more records"', async () => {
    // Review 4, code F2: the sort field is mid-reindex (or was removed) —
    // nothing was queried, and page 1 would be refused the same way.
    pageUrl = '/admin/records/book?sort=price&filter=name%3Aeq%3Ax&after=CURSOR-1';
    pageErrors = { filter: 'reindexing' };
    const view = await mount(<RecordList type={type} records={cursorPage('a', null, 0)} />);
    expect(view.find('[data-testid="records-empty-cursor"]')?.textContent).toBe(
      'Nothing to show — this link could not continue the list.',
    );
    const button = view.find('[data-testid="records-empty-state"]')?.querySelector('button');
    expect(button?.textContent).toBe('Clear filter and sort');
    await click(button);
    expect(lastParams()).toEqual({});
    await view.unmount();
  });
});
