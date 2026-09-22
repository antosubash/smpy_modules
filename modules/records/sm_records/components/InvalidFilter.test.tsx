// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount, setValue } from '../test-dom';
import type { FieldDef, FilterOp } from '../utils/types';

vi.mock('../utils/api-records', () => ({
  getRecord: vi.fn(async () => ({ uuid: 'r1', display_title: 'Dune' })),
}));
vi.mock('../utils/relation-search', () => ({ searchByTitle: vi.fn(async () => []) }));

const { FilterBar } = await import('./FilterBar');

const FIELDS: FieldDef[] = [
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
  },
];

type Applied = { field: string; op: FilterOp; value: string };

async function bar(current: Applied | null) {
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

describe('R7c: "Invalid" is a filter every type has', () => {
  it('offers it as a fixed column, whatever the type declares', async () => {
    const { view } = await bar(null);
    const field = view.find<HTMLSelectElement>('#records-filter-field');
    expect([...(field?.options ?? [])].map((o) => o.value)).toContain('invalid');
    await view.unmount();
  });

  it('applies invalid:eq:true through the same yes/no control a boolean gets', async () => {
    const { view, applied } = await bar(null);
    await setValue(
      view.find<HTMLSelectElement>('#records-filter-field') as HTMLSelectElement,
      'invalid',
    );
    const value = view.find<HTMLSelectElement>('#records-filter-value');
    expect(value?.tagName).toBe('SELECT');
    expect([...(value?.options ?? [])].map((o) => o.value)).toEqual(['true', 'false']);
    (view.find('form') as HTMLFormElement).requestSubmit();
    expect(applied.at(-1)).toEqual({ field: 'invalid', op: 'eq', value: 'true' });
    await view.unmount();
  });

  it('offers only "is" — the server refuses the ordered operators by name', async () => {
    const { view } = await bar({ field: 'invalid', op: 'eq', value: 'true' });
    const op = view.find<HTMLSelectElement>('#records-filter-op');
    expect([...(op?.options ?? [])].map((o) => o.value)).toEqual(['eq']);
    await view.unmount();
  });

  it('repopulates from the URL the hub and the schema report link to', async () => {
    const { view } = await bar({ field: 'invalid', op: 'eq', value: 'true' });
    expect(view.find<HTMLSelectElement>('#records-filter-field')?.value).toBe('invalid');
    expect(view.find<HTMLSelectElement>('#records-filter-value')?.value).toBe('true');
    await view.unmount();
  });
});
