// @vitest-environment happy-dom
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import { availableColumns, MAX_CHOSEN_COLUMNS, resolveListColumns } from '../utils/listing';
import type { FieldDef } from '../utils/types';

/** Just enough of i18next for the panel's interpolated strings — the real
 *  one is unconfigured under vitest and returns templates verbatim. */
function fakeT(key: string, opts?: Record<string, unknown>): string {
  const count = typeof opts?.count === 'number' ? opts.count : undefined;
  const template =
    count !== undefined && count !== 1 && typeof opts?.defaultValue_other === 'string'
      ? opts.defaultValue_other
      : ((opts?.defaultValue as string) ?? key);
  return template.replace(/\{(\w+)\}/g, (_match, name: string) => String(opts?.[name] ?? ''));
}
vi.mock('@simple-module-py/i18n', () => ({ useT: () => ({ t: fakeT }) }));

const { ColumnChooserPanel } = await import('./ColumnChooserPanel');

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
  display_field: null,
  fields: [
    field('price', { type: 'number' }),
    field('author'),
    field('blurb', { type: 'longtext', indexed: false }),
    field('order_status', { label: 'Status' }),
  ],
};

/** The panel is controlled; this holds `?columns=` the way the page does. */
function Harness({
  initial,
  fields = type.fields,
  onKeys,
  onReset,
}: {
  initial: string | null;
  fields?: FieldDef[];
  onKeys?: (keys: string[]) => void;
  onReset?: () => void;
}) {
  const [raw, setRaw] = useState(initial);
  const t = { display_field: null, fields };
  return (
    <ColumnChooserPanel
      available={availableColumns(t, false)}
      resolved={resolveListColumns({ type: t, showLocale: false, raw, saved: null })}
      onChange={(keys) => {
        onKeys?.(keys);
        setRaw(keys.join(','));
      }}
      onReset={() => {
        onReset?.();
        setRaw(null);
      }}
    />
  );
}

type View = Awaited<ReturnType<typeof mount>>;
const rows = (view: View, chosen: 'true' | 'false') =>
  view
    .all(`[data-testid="records-column-option"][data-chosen="${chosen}"]`)
    .map((li) => li.getAttribute('data-column'));
const toggle = (view: View, key: string) => view.find(`#records-column-toggle-${key}`);

describe('ColumnChooserPanel — what it offers', () => {
  it('lists the shown columns first, in order, then the hidden ones', async () => {
    const view = await mount(<Harness initial="author,status" />);
    expect(rows(view, 'true')).toEqual(['author', 'status']);
    expect(rows(view, 'false')).toEqual([
      'position',
      'published_at',
      'updated_at',
      'price',
      'blurb',
      'order_status',
    ]);
    expect(view.find('[data-testid="records-columns-count"]')?.textContent).toBe(
      `1 of ${MAX_CHOSEN_COLUMNS} field column`,
    );
    await view.unmount();
    const two = await mount(<Harness initial="author,price" />);
    expect(two.find('[data-testid="records-columns-count"]')?.textContent).toBe(
      `2 of ${MAX_CHOSEN_COLUMNS} field columns`,
    );
    await two.unmount();
  });

  it('marks indexed fields, and says why a non-indexed one will not sort', async () => {
    const view = await mount(<Harness initial={null} />);
    const blurb = view.find('[data-column="blurb"]');
    expect(blurb?.querySelector('[data-testid="records-column-not-indexed"]')).not.toBeNull();
    expect(blurb?.textContent).toContain('Long text');
    const price = view.find('[data-column="price"]');
    expect(price?.textContent).toContain('Indexed');
    expect(price?.querySelector('[data-testid="records-column-not-indexed"]')).toBeNull();
    expect(price?.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    await view.unmount();
  });

  it('tells a field labelled "Status" apart from the record’s own Status', async () => {
    const view = await mount(<Harness initial={null} />);
    expect(view.find('label[for="records-column-toggle-order_status"]')?.textContent).toBe(
      'Status (order_status)',
    );
    expect(view.find('label[for="records-column-toggle-status"]')?.textContent).toBe(
      'Status (status)',
    );
    await view.unmount();
  });
});

describe('ColumnChooserPanel — toggling', () => {
  it("adds a field after the other fields, before the record's trailing columns", async () => {
    // Review 4, ux F11: a ticked field used to land after Published on/Updated.
    const onKeys = vi.fn();
    const view = await mount(<Harness initial="status,price,updated_at" onKeys={onKeys} />);
    await click(toggle(view, 'blurb'));
    expect(onKeys).toHaveBeenLastCalledWith(['status', 'price', 'blurb', 'updated_at']);
    await click(toggle(view, 'price'));
    await click(toggle(view, 'blurb'));
    // No field shown: before the first trailing record column.
    await click(toggle(view, 'author'));
    expect(onKeys).toHaveBeenLastCalledWith(['status', 'author', 'updated_at']);
    // A record column is appended.
    await click(toggle(view, 'position'));
    expect(onKeys).toHaveBeenLastCalledWith(['status', 'author', 'updated_at', 'position']);
    await view.unmount();
  });

  it('appends a column when ticked and removes it when unticked', async () => {
    const onKeys = vi.fn();
    const view = await mount(<Harness initial="author" onKeys={onKeys} />);
    await click(toggle(view, 'blurb'));
    expect(onKeys).toHaveBeenLastCalledWith(['author', 'blurb']);
    expect(rows(view, 'true')).toEqual(['author', 'blurb']);
    await click(toggle(view, 'author'));
    expect(rows(view, 'true')).toEqual(['blurb']);
    expect(document.activeElement?.id).toBe('records-column-toggle-author');
    await view.unmount();
  });

  it(`stops at ${MAX_CHOSEN_COLUMNS} field columns, leaving the record's own toggles free`, async () => {
    const many = Array.from({ length: MAX_CHOSEN_COLUMNS + 2 }, (_, n) => field(`f${n}`));
    const first = many.slice(0, MAX_CHOSEN_COLUMNS).map((f) => f.key);
    const view = await mount(<Harness initial={first.join(',')} fields={many} />);
    expect(view.find('[data-testid="records-columns-cap"]')).not.toBeNull();
    expect(toggle(view, `f${MAX_CHOSEN_COLUMNS}`)?.hasAttribute('disabled')).toBe(true);
    expect(toggle(view, 'status')?.hasAttribute('disabled')).toBe(false);
    await click(toggle(view, 'f0'));
    expect(view.find('[data-testid="records-columns-cap"]')).toBeNull();
    expect(toggle(view, `f${MAX_CHOSEN_COLUMNS}`)?.hasAttribute('disabled')).toBe(false);
    await view.unmount();
  });
});

describe('ColumnChooserPanel — reordering, from the keyboard', () => {
  it('moves a column with real, named buttons and keeps focus on the moved column', async () => {
    const view = await mount(<Harness initial="price,author,status" />);
    const down = view.find<HTMLButtonElement>('#records-column-down-price');
    expect(down?.tagName).toBe('BUTTON');
    expect(down?.getAttribute('type')).toBe('button');
    expect(down?.getAttribute('aria-label')).toBe('Move Price down');
    expect(view.find<HTMLButtonElement>('#records-column-up-price')?.disabled).toBe(true);

    down?.focus();
    await click(down);
    expect(rows(view, 'true')).toEqual(['author', 'price', 'status']);
    expect(document.activeElement?.id).toBe('records-column-down-price');

    await click(document.activeElement);
    expect(rows(view, 'true')).toEqual(['author', 'status', 'price']);
    // At the bottom its "down" is disabled, so focus lands on its "up".
    expect(document.activeElement?.id).toBe('records-column-up-price');

    await click(document.activeElement);
    expect(rows(view, 'true')).toEqual(['author', 'price', 'status']);
    await view.unmount();
  });

  it('makes every control a focusable button — tick boxes included', async () => {
    const view = await mount(<Harness initial="price,author" />);
    const controls = view.all('[data-testid="records-column-option"] button');
    expect(controls.length).toBeGreaterThan(0);
    for (const control of controls) {
      expect(control.getAttribute('tabindex')).not.toBe('-1');
    }
    expect(toggle(view, 'price')?.getAttribute('role')).toBe('checkbox');
    await view.unmount();
  });
});

describe('ColumnChooserPanel — reset', () => {
  it('is disabled while the list already shows the default', async () => {
    const view = await mount(<Harness initial={null} />);
    const reset = view.find<HTMLButtonElement>('[data-testid="records-columns-reset"]');
    expect(reset?.disabled).toBe(true);
    await view.unmount();
  });

  it('restores the default rule — the first four indexed fields', async () => {
    const onReset = vi.fn();
    const view = await mount(<Harness initial="blurb" onReset={onReset} />);
    const reset = view.find<HTMLButtonElement>('[data-testid="records-columns-reset"]');
    reset?.focus();
    await click(reset);
    expect(onReset).toHaveBeenCalledOnce();
    // Reset is now disabled; focus stays in the panel, on its heading
    // (review 4, ux F10), rather than falling to <body>.
    expect(reset?.disabled).toBe(true);
    expect(document.activeElement?.textContent).toBe('Columns');
    expect(view.host.contains(document.activeElement)).toBe(true);
    expect(rows(view, 'true')).toEqual([
      'status',
      'price',
      'author',
      'order_status',
      'position',
      'published_at',
      'updated_at',
    ]);
    await view.unmount();
  });

  it('says where the choice lives, and that export is unaffected', async () => {
    const view = await mount(<Harness initial={null} />);
    const text = view.host.textContent ?? '';
    expect(text).toContain('?columns=');
    expect(text).toContain('A link that names its own columns wins');
    expect(text).toContain('Export always contains every field');
    await view.unmount();
  });
});
