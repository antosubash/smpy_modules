import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import '../test-dom';
import type { FilterKind } from '../utils/filters';
import type { FieldDef } from '../utils/types';
import { FilterValueInput } from './FilterValueInput';

function field(overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key: 'rank',
    type: 'integer',
    label: 'Rank',
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

/** Attributes of the one `<input>`/`<select>` this renders — a plain string
 *  match is enough here, and avoids pulling in a DOM parser for a single
 *  element. */
function attrs(html: string, name: string): string | null {
  const match = html.match(new RegExp(`${name}="([^"]*)"`));
  return match ? match[1] : null;
}

describe('FilterValueInput — U14: number/integer get a typed control, not bare text', () => {
  it('renders a number input with a decimal keypad hint for "number"', () => {
    const html = renderToStaticMarkup(
      <FilterValueInput
        kind="number"
        field={field({ type: 'number' })}
        value=""
        locales={[]}
        onChange={() => {}}
      />,
    );
    expect(attrs(html, 'type')).toBe('number');
    // React's SSR output keeps this attribute's authored casing
    // (`inputMode`), unlike a plain lowercase HTML attribute.
    expect(attrs(html, 'inputMode')).toBe('decimal');
  });

  it('renders a number input with a numeric keypad hint for "integer"', () => {
    const html = renderToStaticMarkup(
      <FilterValueInput kind="integer" field={field()} value="" locales={[]} onChange={() => {}} />,
    );
    expect(attrs(html, 'type')).toBe('number');
    expect(attrs(html, 'inputMode')).toBe('numeric');
  });

  it('carries the same min/max the editor checks against', () => {
    const html = renderToStaticMarkup(
      <FilterValueInput
        kind="integer"
        field={field({ constraints: { min: 1, max: 10 } })}
        value=""
        locales={[]}
        onChange={() => {}}
      />,
    );
    expect(attrs(html, 'min')).toBe('1');
    expect(attrs(html, 'max')).toBe('10');
  });

  it('leaves min/max off when the field declares no bound', () => {
    const html = renderToStaticMarkup(
      <FilterValueInput
        kind="number"
        field={field({ type: 'number' })}
        value=""
        locales={[]}
        onChange={() => {}}
      />,
    );
    expect(attrs(html, 'min')).toBeNull();
    expect(attrs(html, 'max')).toBeNull();
  });

  it('still falls back to a plain text box for a fixed column with no field ("kind" other than a schema type)', () => {
    const html = renderToStaticMarkup(
      <FilterValueInput
        kind={'text' as FilterKind}
        field={undefined}
        value=""
        locales={[]}
        onChange={() => {}}
      />,
    );
    expect(attrs(html, 'type')).not.toBe('number');
  });
});
