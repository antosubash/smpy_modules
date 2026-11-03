import type { ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DividerWidget } from './divider-widget';

// Puck passes its own `id`/`puck` props alongside the authored ones; the widget
// reads none of them, so these tests supply the authored props alone.
const Divider = DividerWidget.render as unknown as (props: Record<string, unknown>) => ReactElement;

function html(props: Record<string, unknown> = {}): string {
  return renderToStaticMarkup(<Divider {...DividerWidget.defaultProps} {...props} />);
}

describe('DividerWidget measure', () => {
  // Divider is a primitive: like Image it renders no container, so on a page
  // whose root is `full` — which any page built from the section widgets must
  // be — the rule ran the entire width of the viewport instead of closing the
  // section it belongs to.

  it('offers the same Max width options as the other root-level blocks', () => {
    const field = DividerWidget.fields?.maxWidth as { options?: { value: string }[] };
    expect(field?.options?.map((o) => o.value)).toEqual(['2xl', '3xl', '4xl', '5xl', 'full']);
  });

  it('defaults to full width, so existing pages do not move', () => {
    expect(DividerWidget.defaultProps?.maxWidth).toBe('full');
    expect(html()).not.toContain('mx-auto');
  });

  it('caps and centres the rule when constrained', () => {
    const markup = html({ maxWidth: '4xl' });
    expect(markup).toContain('max-w-4xl');
    expect(markup).toContain('mx-auto');
  });

  it('keeps its stroke controls working alongside the measure', () => {
    // The measure must not disturb thickness/style, which share the class list.
    const markup = html({ maxWidth: '3xl', thickness: 'thick', style: 'dashed' });
    expect(markup).toContain('border-t-4');
    expect(markup).toContain('border-dashed');
    expect(markup).toContain('max-w-3xl');
  });

  it('still renders an <hr> carrying its colour', () => {
    expect(html({ color: '#ff0000' })).toMatch(/<hr[^>]*border-color:#ff0000/);
  });
});
