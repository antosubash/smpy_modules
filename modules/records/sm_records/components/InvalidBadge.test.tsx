// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount } from '../test-dom';
import type { FieldDef, RecordRead, TypeRead } from '../utils/types';

vi.mock('@inertiajs/react', () => ({
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
}));

const { RecordTable } = await import('./RecordTable');
const { RecordCardList } = await import('./RecordCardList');

function type(): TypeRead {
  return {
    key: 'product',
    label: 'Product',
    label_plural: 'Products',
    display_field: 'name',
    fields: [
      {
        key: 'name',
        type: 'text',
        label: 'Name',
        required: false,
        unique: false,
        indexed: true,
        default: null,
        help: null,
        constraints: {},
        options: {},
      } as FieldDef,
    ],
  } as TypeRead;
}

function record(invalidSince: string | null): RecordRead {
  return {
    uuid: 'r1',
    type_key: 'product',
    status: 'draft',
    slug: null,
    locale: 'en',
    translation_group: null,
    display_title: 'Widget',
    position: 0,
    version: 1,
    schema_version: 1,
    published_at: null,
    created_at: '2026-01-01T00:00:00+00:00',
    updated_at: '2026-01-01T00:00:00+00:00',
    is_deleted: false,
    data: {},
    // Empty on every list row by construction — which is the whole reason
    // the badge reads the stored column instead.
    invalid: [],
    invalid_since: invalidSince,
  } as unknown as RecordRead;
}

const noop = async () => undefined;

const table = (invalidSince: string | null) => (
  <RecordTable
    type={type()}
    records={[record(invalidSince)]}
    sort={null}
    onSort={() => {}}
    onDelete={noop}
    onRestore={noop}
    onPurge={noop}
  />
);

const cards = (invalidSince: string | null) => (
  <RecordCardList
    type={type()}
    records={[record(invalidSince)]}
    onDelete={noop}
    onRestore={noop}
    onPurge={noop}
  />
);

describe('R7c: the row says a record does not satisfy its schema', () => {
  it('badges a marked row in the table', async () => {
    const view = await mount(table('2026-02-03T10:00:00+00:00'));
    const badge = view.find('[data-testid="records-invalid-badge"]');
    expect(badge?.textContent).toBe('Invalid');
    // The tooltip names the date rather than the fields: those cost a
    // validator pass per row that the list deliberately does not pay.
    expect(badge?.getAttribute('title')).toContain('has not satisfied its schema since');
    await view.unmount();
  });

  it('badges a marked card at phone width', async () => {
    const view = await mount(cards('2026-02-03T10:00:00+00:00'));
    expect(view.find('[data-testid="records-invalid-badge"]')).not.toBeNull();
    await view.unmount();
  });

  it('says nothing about a record nothing has found wanting', async () => {
    const view = await mount(table(null));
    expect(view.find('[data-testid="records-invalid-badge"]')).toBeNull();
    await view.unmount();
    const cardView = await mount(cards(null));
    expect(cardView.find('[data-testid="records-invalid-badge"]')).toBeNull();
    await cardView.unmount();
  });
});
