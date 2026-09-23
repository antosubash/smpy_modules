// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import { columnStorageKey } from '../utils/column-storage';
import type { FieldDef, RecordPage, RecordRead, TypeRead } from '../utils/types';

let pageUrl = '/admin/records/book';
let ioSearch: string | undefined;
let pageErrors: Record<string, string> = {};
const get = vi.fn();
const replace = vi.fn();

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
  usePage: () => ({ url: pageUrl, props: { errors: pageErrors, auth: { permissions: [] } } }),
  router: { get, replace, reload: vi.fn(), visit: vi.fn() },
}));
vi.mock('../components/RecordIoMenu', () => ({
  RecordIoMenu: ({ search }: { search: string }) => {
    ioSearch = search;
    return null;
  },
}));
vi.mock('../components/RecordsToaster', () => ({ RecordsToaster: () => null }));
// i18next is unconfigured under vitest and returns templates verbatim; the
// notice names the dropped keys only through interpolation.
vi.mock('@simple-module-py/i18n', () => {
  const t = (key: string, opts?: Record<string, unknown>) =>
    String(opts?.defaultValue ?? key).replace(/\{(\w+)\}/g, (_m, name: string) =>
      String(opts?.[name] ?? ''),
    );
  return { t, useT: () => ({ t }) };
});

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

function records(): RecordPage {
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
      data: { price: '1', author: 'A', blurb: 'B' },
    }) as unknown as RecordRead;
  return {
    items: [item('r1'), item('r2')],
    total: 100,
    total_capped: false,
    page: 1,
    page_size: 25,
    next_cursor: null,
  };
}

/** The params of a `router.get` — the page passes the whole URL. */
const getParams = (call = 0) =>
  Object.fromEntries(new URL(String(get.mock.calls[call][0]), 'http://x').searchParams);

type View = Awaited<ReturnType<typeof mount>>;
const headers = (view: View) =>
  view.all('thead th').map((th) => th.textContent?.replace(/[▲▼]/g, '').trim());
const saved = () => window.localStorage.getItem(columnStorageKey('book'));

async function openPanel(view: View) {
  await click(view.find('[data-testid="records-columns-button"]'));
  return document.body.querySelector('[data-testid="records-columns-panel"]');
}

beforeEach(() => {
  get.mockClear();
  replace.mockClear();
  window.localStorage.clear();
  pageUrl = '/admin/records/book';
  pageErrors = {};
});
afterEach(() => window.localStorage.clear());

describe('RecordList — ?columns= decides the table', () => {
  it('renders exactly the columns the link names, in its order', async () => {
    pageUrl = '/admin/records/book?columns=blurb,updated_at,price';
    const view = await mount(<RecordList type={type} records={records()} />);
    expect(headers(view)).toEqual(['Title', 'Blurb', 'Updated', 'Price', 'Actions']);
    expect(view.find('[data-testid="records-columns-notice"]')).toBeNull();
    await view.unmount();
  });

  it('drops a key the type does not have, with a notice rather than an error', async () => {
    pageUrl = '/admin/records/book?columns=price,nope';
    const view = await mount(<RecordList type={type} records={records()} />);
    expect(headers(view)).toEqual(['Title', 'Price', 'Actions']);
    expect(view.find('[data-testid="records-columns-notice"]')?.textContent).toContain('nope');
    await view.unmount();
  });

  it('carries the choice through a page change, and keeps it out of the export', async () => {
    pageUrl = '/admin/records/book?columns=price,author';
    const view = await mount(<RecordList type={type} records={records()} />);
    await click(view.button('Next'));
    expect(getParams()).toMatchObject({ page: '2', columns: 'price,author' });
    expect(ioSearch).toBe('');
    await view.unmount();
  });
});

describe('RecordList — the per-browser default', () => {
  it('applies the saved choice when the link has none, without touching the URL', async () => {
    window.localStorage.setItem(columnStorageKey('book'), JSON.stringify(['author', 'blurb']));
    const view = await mount(<RecordList type={type} records={records()} />);
    expect(headers(view)).toEqual(['Title', 'Author', 'Blurb', 'Actions']);
    expect(replace).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('lets a link that names its own columns win over the saved choice', async () => {
    window.localStorage.setItem(columnStorageKey('book'), JSON.stringify(['author']));
    pageUrl = '/admin/records/book?columns=blurb';
    const view = await mount(<RecordList type={type} records={records()} />);
    expect(headers(view)).toEqual(['Title', 'Blurb', 'Actions']);
    expect(saved()).toBe('["author"]');
    await view.unmount();
  });

  it('falls back to the default for an unparsable saved value', async () => {
    window.localStorage.setItem(columnStorageKey('book'), '{oops');
    const view = await mount(<RecordList type={type} records={records()} />);
    expect(headers(view)).toEqual([
      'Title',
      'Status',
      'Price',
      'Author',
      'Published on',
      'Updated',
      'Actions',
    ]);
    await view.unmount();
  });
});

describe('RecordList — changing columns', () => {
  it('writes the link (commas left readable) and the saved choice, client-side', async () => {
    pageUrl = '/admin/records/book?filter=author:eq:A&columns=price';
    const view = await mount(<RecordList type={type} records={records()} />);
    const panel = await openPanel(view);
    expect(panel).not.toBeNull();
    await click(document.body.querySelector('#records-column-toggle-blurb'));
    expect(replace).toHaveBeenCalledOnce();
    expect(replace.mock.calls[0][0]).toMatchObject({
      url: '/admin/records/book?filter=author%3Aeq%3AA&columns=price,blurb',
      preserveState: true,
    });
    expect(saved()).toBe('["price","blurb"]');
    expect(get).not.toHaveBeenCalled();
    await view.unmount();
  });

  it('starts from what the table shows: an all-zero Position stays out of the choice', async () => {
    const view = await mount(<RecordList type={type} records={records()} />);
    await openPanel(view);
    const position = document.body.querySelector('[data-column="position"]');
    expect(position?.getAttribute('data-chosen')).toBe('false');
    await click(document.body.querySelector('#records-column-toggle-blurb'));
    expect(replace.mock.calls[0][0].url).toBe(
      '/admin/records/book?columns=status,price,author,blurb,published_at,updated_at',
    );
    await view.unmount();
  });

  it('drops a sort whose column is hidden, through the usual list navigation', async () => {
    pageUrl = '/admin/records/book?sort=-price&columns=price,author';
    const view = await mount(<RecordList type={type} records={records()} />);
    await openPanel(view);
    await click(document.body.querySelector('#records-column-toggle-price'));
    expect(replace).not.toHaveBeenCalled();
    expect(get).toHaveBeenCalledOnce();
    const params = getParams();
    expect(params.sort).toBeUndefined();
    expect(params.columns).toBe('author');
    await view.unmount();
  });

  it('keeps a sort whose column stays shown', async () => {
    pageUrl = '/admin/records/book?sort=author&columns=price,author';
    const view = await mount(<RecordList type={type} records={records()} />);
    await openPanel(view);
    await click(document.body.querySelector('#records-column-toggle-price'));
    expect(get).not.toHaveBeenCalled();
    expect(replace.mock.calls[0][0].url).toBe('/admin/records/book?sort=author&columns=author');
    await view.unmount();
  });

  it('"Reset to default" clears both the link and the saved choice', async () => {
    window.localStorage.setItem(columnStorageKey('book'), JSON.stringify(['author']));
    pageUrl = '/admin/records/book?page=2&columns=blurb';
    const view = await mount(<RecordList type={type} records={{ ...records(), page: 2 }} />);
    await openPanel(view);
    await click(document.body.querySelector('[data-testid="records-columns-reset"]'));
    expect(saved()).toBeNull();
    expect(replace.mock.calls[0][0].url).toBe('/admin/records/book?page=2');
    await view.unmount();
  });
});

describe('RecordList — columns on a page reached by cursor', () => {
  const cursorPage = (items: RecordPage['items']) => ({
    ...records(),
    items,
    total_capped: true,
    page: null,
    next_cursor: items.length ? 'NEXT' : null,
  });

  it('Next page keeps the columns; a column change keeps the cursor', async () => {
    pageUrl = '/admin/records/book?after=CUR&sort=author&columns=price,author';
    const view = await mount(<RecordList type={type} records={cursorPage(records().items)} />);
    await click(view.button('Next page'));
    expect(getParams()).toEqual({ after: 'NEXT', sort: 'author', columns: 'price,author' });
    await openPanel(view);
    await click(document.body.querySelector('#records-column-toggle-blurb'));
    expect(replace.mock.calls[0][0].url).toBe(
      '/admin/records/book?after=CUR&sort=author&columns=price,author,blurb',
    );
    await view.unmount();
  });

  it('an empty or refused cursor page keeps the Columns menu', async () => {
    pageUrl = '/admin/records/book?after=CUR&columns=price';
    const ended = await mount(<RecordList type={type} records={cursorPage([])} />);
    expect(ended.find('[data-testid="records-columns-button"]')).not.toBeNull();
    await ended.unmount();
    pageErrors = { filter: 'bad_cursor' };
    const refused = await mount(<RecordList type={type} records={cursorPage([])} />);
    expect(refused.find('[data-testid="records-filter-error"]')).not.toBeNull();
    expect(refused.find('[data-testid="records-columns-button"]')).not.toBeNull();
    await refused.unmount();
  });
});
