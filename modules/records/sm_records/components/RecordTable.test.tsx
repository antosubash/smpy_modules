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

function field(overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key: 'note',
    type: 'text',
    label: 'Note',
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...overrides,
  };
}

function type(overrides: Partial<TypeRead> = {}): TypeRead {
  return {
    key: 'qa_ux_event',
    label: 'QA UX Event',
    label_plural: 'QA UX Events',
    display_field: 'title',
    fields: [field()],
    ...overrides,
  } as TypeRead;
}

function record(): RecordRead {
  return {
    uuid: 'r1',
    type_key: 'qa_ux_event',
    status: 'draft',
    slug: null,
    locale: 'en',
    translation_group: null,
    display_title: 'Autumn Summit',
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

const noop = async () => undefined;

describe('RecordTable — U6: a type with no indexed field says so under the table', () => {
  it('renders the notice, linking to the type editor, when listColumns is empty', async () => {
    const view = await mount(
      <RecordTable
        type={type()}
        records={[record()]}
        sort={null}
        onSort={() => {}}
        onDelete={noop}
        onRestore={noop}
        onPurge={noop}
      />,
    );
    const notice = view.find('[data-testid="records-no-indexed-columns"]');
    expect(notice).not.toBeNull();
    expect(notice?.textContent).toContain('No fields are indexed');
    const link = view.find<HTMLAnchorElement>('[data-testid="records-no-indexed-columns"] a');
    expect(link?.getAttribute('href')).toBe('/admin/records/types/qa_ux_event');
    await view.unmount();
  });

  it('says nothing once a field is indexed', async () => {
    const view = await mount(
      <RecordTable
        type={type({ fields: [field({ indexed: true })] })}
        records={[record()]}
        sort={null}
        onSort={() => {}}
        onDelete={noop}
        onRestore={noop}
        onPurge={noop}
      />,
    );
    expect(view.find('[data-testid="records-no-indexed-columns"]')).toBeNull();
    await view.unmount();
  });
});
