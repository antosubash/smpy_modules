// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import type { FieldDef, RecordRead, TypeRead } from '../utils/types';

vi.mock('@inertiajs/react', () => ({
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
}));

const { RecordCardList } = await import('./RecordCardList');
const { useRecordSelection } = await import('../hooks/useRecordSelection');

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

function record(overrides: Partial<RecordRead> = {}): RecordRead {
  return {
    uuid: '3f2a1c9e84b34e0e9a1b2c3d4e5f6789',
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
    ...overrides,
  } as unknown as RecordRead;
}

const noop = async () => undefined;

/** A real selection behind the card list — same reasoning as
 *  `RecordTable.test.tsx`'s own `Selectable`: mocking the hook would test
 *  the mock. */
function Selectable({ records }: { records: RecordRead[] }) {
  const selection = useRecordSelection(records.map((r) => r.uuid));
  return (
    <>
      <output data-testid="picked">{selection.uuids.join(',')}</output>
      <RecordCardList
        type={type()}
        records={records}
        selection={selection}
        onDelete={noop}
        onRestore={noop}
        onPurge={noop}
      />
    </>
  );
}

describe('RecordCardList — U6: a select-all control below md, mirroring the table header', () => {
  it('offers none of it without a selection — a viewer gets no inert boxes', async () => {
    const view = await mount(
      <RecordCardList
        type={type()}
        records={[record()]}
        onDelete={noop}
        onRestore={noop}
        onPurge={noop}
      />,
    );
    expect(view.find('[data-testid="records-card-select-all"]')).toBeNull();
    await view.unmount();
  });

  it('ticks every card on the page, and again clears them', async () => {
    const rows = [record(), record({ uuid: 'r2', display_title: 'Second' })];
    const view = await mount(<Selectable records={rows} />);

    const header = view.find('[data-testid="records-card-select-all"]');
    expect(header).not.toBeNull();
    const box = header?.querySelector('button[role="checkbox"]');

    await click(box);
    expect(view.find('[data-testid="picked"]')?.textContent).toBe(
      '3f2a1c9e84b34e0e9a1b2c3d4e5f6789,r2',
    );

    await click(box);
    expect(view.find('[data-testid="picked"]')?.textContent).toBe('');
    await view.unmount();
  });
});

describe('RecordCardList — U5: an empty display title still gets a name', () => {
  it('falls back to the type label and the short uuid in the title link', async () => {
    const view = await mount(
      <RecordCardList
        type={type()}
        records={[record({ display_title: '' })]}
        onDelete={noop}
        onRestore={noop}
        onPurge={noop}
      />,
    );
    const link = view.find('[data-testid="records-record-card"] a');
    expect(link?.textContent).toBe('QA UX Event 3f2a1c9e…');
    await view.unmount();
  });
});
