// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import { resolveListColumns } from '../utils/listing';
import type { FieldDef, RecordRead, TypeRead } from '../utils/types';

vi.mock('@inertiajs/react', () => ({
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
}));

const { RecordTable } = await import('./RecordTable');
const { RecordCardList, CARD_COLUMNS } = await import('./RecordCardList');

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
  display_field: null,
  fields: [
    field('price', { type: 'number' }),
    field('author'),
    field('blurb', { type: 'longtext', indexed: false }),
    field('meta', { type: 'json', indexed: false }),
  ],
} as unknown as TypeRead;

function record(overrides: Partial<RecordRead> = {}): RecordRead {
  return {
    uuid: 'r1',
    type_key: 'book',
    status: 'draft',
    locale: 'en',
    display_title: 'Dune',
    position: 0,
    published_at: null,
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
    data: { price: '9.5', author: 'Herbert', blurb: 'Sand.\n\nWorms.', meta: { a: 1 } },
    ...overrides,
  } as unknown as RecordRead;
}

const noop = async () => undefined;
const chosen = (raw: string) => resolveListColumns({ type, showLocale: false, raw, saved: null });

async function table(raw: string | null, records = [record()], sort = null, onSort = () => {}) {
  return mount(
    <RecordTable
      type={type}
      records={records}
      sort={sort}
      columns={raw === null ? undefined : chosen(raw)}
      onSort={onSort}
      onDelete={noop}
      onRestore={noop}
      onPurge={noop}
    />,
  );
}

const headers = (view: Awaited<ReturnType<typeof mount>>) =>
  view.all('thead th').map((th) => th.textContent?.replace(/[▲▼]/g, '').trim());

describe('RecordTable — renders the chosen columns, in the chosen order', () => {
  it('puts Title first and Actions last around exactly the chosen set', async () => {
    const view = await table('blurb,updated_at,price');
    expect(headers(view)).toEqual(['Title', 'Blurb', 'Updated', 'Price', 'Actions']);
    const cells = view.all('tbody tr td').map((td) => td.textContent);
    expect(cells[1]).toBe('Sand. Worms.');
    expect(cells[3]).toBe((9.5).toLocaleString());
    await view.unmount();
  });

  it('gives a non-indexed column no sort control, and says why', async () => {
    const onSort = vi.fn();
    const view = await table('meta,price', [record()], null, onSort);
    const plain = view.find('[data-testid="records-column-unsortable"]');
    expect(plain?.getAttribute('data-column')).toBe('meta');
    expect(plain?.querySelector('button')).toBeNull();
    expect(plain?.querySelector('[title]')?.getAttribute('title')).toContain('Not indexed');
    await click(view.all('thead button').find((b) => b.textContent?.includes('Price')));
    expect(onSort).toHaveBeenCalledWith('price');
    await view.unmount();
  });

  it('moves the Invalid marker beside the title when Status is hidden', async () => {
    const flagged = record({ invalid_since: '2026-01-02T00:00:00+00:00' } as Partial<RecordRead>);
    const view = await table('price', [flagged]);
    const titleCell = view.all('tbody td')[0];
    expect(titleCell.querySelector('[data-testid="records-invalid-badge"]')).not.toBeNull();
    expect(view.all('[data-testid="records-invalid-badge"]')).toHaveLength(1);
    await view.unmount();
    const withStatus = await table('status,price', [flagged]);
    expect(
      withStatus.all('tbody td')[0].querySelector('[data-testid="records-invalid-badge"]'),
    ).toBeNull();
    expect(withStatus.all('[data-testid="records-invalid-badge"]')).toHaveLength(1);
    await withStatus.unmount();
  });

  it('hides an all-zero Position in the default view, but shows it once chosen', async () => {
    const byDefault = await table(null);
    expect(headers(byDefault)).not.toContain('Position');
    expect(headers(byDefault)).toEqual([
      'Title',
      'Status',
      'Price',
      'Author',
      'Published on',
      'Updated',
      'Actions',
    ]);
    await byDefault.unmount();
    const chosenView = await table('position');
    expect(headers(chosenView)).toEqual(['Title', 'Position', 'Actions']);
    await chosenView.unmount();
  });

  it('does not show the no-indexed-fields notice for a view that chose its own columns', async () => {
    const view = await table('blurb');
    expect(view.find('[data-testid="records-no-indexed-columns"]')).toBeNull();
    await view.unmount();
  });
});

describe('RecordCardList — the first chosen columns, in order', () => {
  async function cards(raw: string) {
    return mount(
      <RecordCardList
        type={type}
        records={[record()]}
        columns={chosen(raw).columns}
        onDelete={noop}
        onRestore={noop}
        onPurge={noop}
      />,
    );
  }

  it(`lists the first ${CARD_COLUMNS} chosen columns as label/value lines`, async () => {
    const view = await cards('author,meta,updated_at,price,blurb');
    const labels = view.all('dt').map((dt) => dt.textContent);
    expect(labels).toEqual(['Author', 'Meta', 'Updated']);
    expect(view.all('dd').map((dd) => dd.getAttribute('data-column'))).toEqual([
      'author',
      'meta',
      'updated_at',
    ]);
    await view.unmount();
  });

  it('renders Status as a badge, not one of the lines, and only when chosen', async () => {
    const withStatus = await cards('status,price');
    expect(withStatus.all('dt').map((dt) => dt.textContent)).toEqual(['Price']);
    expect(withStatus.host.textContent).toContain('Draft');
    await withStatus.unmount();
    const without = await cards('price');
    expect(without.host.textContent).not.toContain('Draft');
    await without.unmount();
  });
});

describe('RecordTable — a field labelled like a record column (review 4, ux F3)', () => {
  const clash = {
    ...type,
    fields: [
      field('state', { type: 'select', label: 'Status' }),
      field('changed', { type: 'date', label: 'Updated' }),
      field('rank', { type: 'integer', label: 'Position' }),
      field('title', { label: 'Title' }),
    ],
  } as unknown as TypeRead;
  const shown = resolveListColumns({
    type: clash,
    showLocale: false,
    raw: 'status,state,changed,updated_at,rank,position,title',
    saved: null,
  });
  const row = record({ position: 3, data: { state: 'x', changed: null, rank: 1, title: 'T' } });

  it('gives every header an unambiguous name, as the Columns panel does', async () => {
    const view = await mount(
      <RecordTable
        type={clash}
        records={[row]}
        sort={null}
        columns={shown}
        onSort={() => {}}
        onDelete={noop}
        onRestore={noop}
        onPurge={noop}
      />,
    );
    expect(headers(view)).toEqual([
      'Title',
      'Status (status)',
      'Status (state)',
      'Updated (changed)',
      'Updated (updated_at)',
      'Position (rank)',
      'Position (position)',
      'Title (title)',
      'Actions',
    ]);
    const names = view
      .all('thead button')
      .map((b) => b.getAttribute('aria-label') ?? b.textContent);
    expect(new Set(names).size).toBe(names.length);
    await view.unmount();
  });

  it('labels a card line the same way, beside the status badge', async () => {
    const view = await mount(
      <RecordCardList
        type={clash}
        records={[row]}
        columns={shown.columns.filter((c) => c.key === 'status' || c.key === 'state')}
        onDelete={noop}
        onRestore={noop}
        onPurge={noop}
      />,
    );
    expect(view.all('dt').map((dt) => dt.textContent)).toEqual(['Status (state)']);
    await view.unmount();
  });
});
