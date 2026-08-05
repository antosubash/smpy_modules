/**
 * Smoke coverage for the whole block catalogue.
 *
 * The e2e suite proves a handful of widgets reach the DOM; it can't afford a
 * page per block. This renders every entry with its own `defaultProps`, which
 * is what an author gets the moment they drag one in — so a widget that throws
 * on first paint fails here rather than as a blank section on someone's page.
 */

import type { ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { catalogCategories, catalogComponents } from './widgetCatalog';

type AnyConfig = {
  label?: string;
  fields?: Record<string, { type?: string }>;
  defaultProps?: Record<string, unknown>;
  render: ComponentType<Record<string, unknown>>;
};

const entries = Object.entries(catalogComponents) as [string, AnyConfig][];

/** A slot arrives at `render` as a component; stored data holds an array. */
const SlotStub = () => null;

/**
 * Swap every slot field's stored array for the component Puck would inject.
 * Without this the layout blocks throw on `<Content />`, which would be this
 * test failing on its own setup rather than on the widget.
 */
function withSlotsResolved(config: AnyConfig): Record<string, unknown> {
  const props: Record<string, unknown> = { ...(config.defaultProps ?? {}) };
  for (const [name, field] of Object.entries(config.fields ?? {})) {
    if (field?.type === 'slot') props[name] = SlotStub;
  }
  // Slots nested in array items (Columns keeps one per column) need the same
  // treatment a level down.
  for (const [name, field] of Object.entries(config.fields ?? {})) {
    const arrayFields = (field as { arrayFields?: Record<string, { type?: string }> }).arrayFields;
    if (!arrayFields || !Array.isArray(props[name])) continue;
    const slotKeys = Object.entries(arrayFields)
      .filter(([, f]) => f?.type === 'slot')
      .map(([k]) => k);
    if (slotKeys.length === 0) continue;
    props[name] = (props[name] as Record<string, unknown>[]).map((item) => ({
      ...item,
      ...Object.fromEntries(slotKeys.map((k) => [k, SlotStub])),
    }));
  }
  return props;
}

describe('catalogue structure', () => {
  it('files every block under exactly one category', () => {
    const filed = Object.values(catalogCategories).flatMap((c) => c.components);
    const duplicated = filed.filter((name, i) => filed.indexOf(name) !== i);
    expect(duplicated).toEqual([]);
    expect([...filed].sort()).toEqual(Object.keys(catalogComponents).sort());
  });

  it('gives every block a label', () => {
    // Puck falls back to the raw key, so a missing label is not a crash — it
    // just shows the author "ColoredActionList" instead of "Action list".
    const unlabelled = entries.filter(([, c]) => !c.label).map(([name]) => name);
    expect(unlabelled).toEqual([]);
  });

  it('gives every field a default', () => {
    // A field with no default renders as `undefined` on first drop, which is
    // how a widget ends up blank until the author touches every input.
    const gaps = entries.flatMap(([name, c]) =>
      Object.keys(c.fields ?? {})
        .filter((f) => !(f in (c.defaultProps ?? {})))
        .map((f) => `${name}.${f}`),
    );
    expect(gaps).toEqual([]);
  });
});

describe('every block renders with its defaults', () => {
  it.each(entries.map(([name, config]) => ({ name, config })))('$name', ({ config }) => {
    const Render = config.render;
    const html = renderToStaticMarkup(<Render {...withSlotsResolved(config)} />);
    expect(typeof html).toBe('string');
  });
});
