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
    // The real assertion is that this line doesn't throw. `toBe('string')`
    // could never fail — renderToStaticMarkup always returns one — so it said
    // nothing about the widget. Requiring output also catches a block that
    // renders to nothing at all with its own defaults.
    const html = renderToStaticMarkup(<Render {...withSlotsResolved(config)} />);
    expect(html).not.toBe('');
  });
});

describe('blocks tolerate data stored before a field existed', () => {
  // `defaultProps` only covers a block dropped *now*. A Button saved before
  // `size` existed arrives without it, and `sizeClass[undefined]` yields
  // `undefined` — which `cn()` silently drops, so the button renders with no
  // size classes at all rather than crashing. Nothing in a normal suite
  // notices, because every other fixture is built from the current defaults.
  //
  // So the assertion is that the *expected class* is present. Checking the
  // output merely doesn't say "undefined" passes even with the default
  // removed, which is how the first version of this test was useless.
  const cases: { name: string; props: Record<string, unknown>; expected: string[] }[] = [
    {
      name: 'Button',
      props: { label: 'Old', href: '/x', variant: 'primary', target: '_self' },
      expected: ['px-5', 'bg-primary-700'],
    },
    // Every asserted class must come from a prop the case OMITS, otherwise the
    // assertion is satisfied by the explicit prop and the default it is meant
    // to guard can be deleted with the test still green.
    { name: 'Text', props: { text: 'Old copy.' }, expected: ['text-base', 'text-left'] },
    { name: 'Heading', props: { text: 'Old' }, expected: ['text-3xl', 'text-left'] },
  ];

  it.each(cases)('$name', ({ name, props, expected }) => {
    const config = catalogComponents[name as keyof typeof catalogComponents] as AnyConfig;
    const Render = config.render;
    const html = renderToStaticMarkup(<Render {...props} />);
    for (const cls of expected) expect(html).toContain(cls);
  });
});
