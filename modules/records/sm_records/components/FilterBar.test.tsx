// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount, setValue } from '../test-dom';
import type { FieldDef, FilterOp } from '../utils/types';

vi.mock('../utils/api-records', () => ({
  getRecord: vi.fn(async () => ({ uuid: 'r1', display_title: 'Dune' })),
}));
vi.mock('../utils/relation-search', () => ({ searchByTitle: vi.fn(async () => []) }));

const { FilterBar } = await import('./FilterBar');

function field(overrides: Partial<FieldDef>): FieldDef {
  return {
    key: 'f',
    type: 'text',
    label: 'F',
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

const FIELDS = [
  field({ key: 'flag', type: 'boolean', label: 'Flag' }),
  field({ key: 'due', type: 'date', label: 'Due' }),
  field({ key: 'seen_at', type: 'datetime', label: 'Seen at' }),
  field({
    key: 'author',
    type: 'relation',
    label: 'Author',
    options: { target_type: 'person' },
  }),
];

type Applied = { field: string; op: FilterOp; value: string };

async function bar(current: { field: string; op: FilterOp; value: string } | null) {
  const applied: Applied[] = [];
  const view = await mount(
    <FilterBar
      fields={FIELDS}
      current={current}
      onApply={(f, op, value) => applied.push({ field: f, op, value })}
      onClear={() => {}}
    />,
  );
  return { view, applied };
}

describe('FilterBar — R8/M12: a control per kind, same URL grammar', () => {
  it('offers a true/false select for a boolean field', async () => {
    const { view, applied } = await bar({ field: 'flag', op: 'eq', value: 'true' });
    const value = view.find<HTMLSelectElement>('#records-filter-value');
    expect(value?.tagName).toBe('SELECT');
    expect([...(value?.options ?? [])].map((o) => o.value)).toEqual(['true', 'false']);

    await setValue(value as HTMLSelectElement, 'false');
    (view.find('form') as HTMLFormElement).requestSubmit();
    expect(applied.at(-1)).toEqual({ field: 'flag', op: 'eq', value: 'false' });
    await view.unmount();
  });

  it('offers a date picker whose value is the wire value', async () => {
    const { view, applied } = await bar({ field: 'due', op: 'eq', value: '2026-01-15' });
    const value = view.find<HTMLInputElement>('#records-filter-value');
    expect(value?.type).toBe('date');
    expect(value?.value).toBe('2026-01-15');
    (view.find('form') as HTMLFormElement).requestSubmit();
    expect(applied.at(-1)?.value).toBe('2026-01-15');
    await view.unmount();
  });

  it('offers a datetime picker and sends an offset-carrying value', async () => {
    // `coerce_datetime` refuses a naive value rather than guessing a zone,
    // so the control's local string has to be stamped on the way out.
    const { view, applied } = await bar(null);
    await setValue(
      view.find<HTMLSelectElement>('#records-filter-field') as HTMLSelectElement,
      'seen_at',
    );
    const value = view.find<HTMLInputElement>('#records-filter-value');
    expect(value?.type).toBe('datetime-local');
    await setValue(value as HTMLInputElement, '2026-01-15T10:30:00');
    (view.find('form') as HTMLFormElement).requestSubmit();
    expect(applied.at(-1)?.field).toBe('seen_at');
    expect(applied.at(-1)?.value).toMatch(/^2026-01-15T10:30:00[+-]\d{2}:\d{2}$/);
    await view.unmount();
  });

  it('repopulates a datetime picker from a shared URL', async () => {
    const iso = new Date('2026-01-15T10:30:00Z').toISOString();
    const { view } = await bar({ field: 'seen_at', op: 'gte', value: iso });
    const value = view.find<HTMLInputElement>('#records-filter-value');
    // (happy-dom drops a trailing `:00` from a datetime-local value.)
    expect(value?.value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/);
    await view.unmount();
  });

  it('offers the relation combobox instead of a uuid text box', async () => {
    const { view } = await bar({ field: 'author', op: 'eq', value: '' });
    expect(view.find('[data-testid="records-relation-author"]')).not.toBeNull();
    expect(view.find('input[role="combobox"]')).not.toBeNull();
    await view.unmount();
  });

  it('resets the value when the new field needs a different control', async () => {
    const { view } = await bar({ field: 'due', op: 'eq', value: '2026-01-15' });
    await setValue(
      view.find<HTMLSelectElement>('#records-filter-field') as HTMLSelectElement,
      'flag',
    );
    // A date string has no place in a true/false select.
    expect(view.find<HTMLSelectElement>('#records-filter-value')?.value).toBe('true');
    await view.unmount();
  });

  it('ignores a URL value the select has no option for', async () => {
    const { view, applied } = await bar({ field: 'flag', op: 'eq', value: 'maybe' });
    const value = view.find<HTMLSelectElement>('#records-filter-value');
    expect(value?.value).toBe('true');
    (view.find('form') as HTMLFormElement).requestSubmit();
    // …and Apply submits what is on screen, not the value that just failed.
    expect(applied.at(-1)?.value).toBe('true');
    await view.unmount();
  });
});
