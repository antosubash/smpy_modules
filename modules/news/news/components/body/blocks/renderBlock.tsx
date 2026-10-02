/**
 * Render one block to static markup, for the block tests next door.
 *
 * Shared rather than copied into each test file so the three cannot drift into
 * disagreeing about what "rendered with its defaults" means — which is the
 * premise every back-compatibility assertion here rests on.
 *
 * Typed structurally instead of as `ComponentConfig<T>`: the tests pass blocks
 * with seven different prop shapes, and the one generic that would accept them
 * all is `never`, which has no `render` to reach for.
 */

import type { ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

interface Renderable {
  render: unknown;
  defaultProps?: unknown;
}

/**
 * `block`'s markup, given its own defaults plus `props`.
 *
 * Puck also passes `id` and a `puck` bag alongside the authored props. No block
 * in this palette reads either, so the tests supply the authored props alone —
 * if one ever does, this is where the fake would go.
 */
export function renderBlock(block: Renderable, props: Record<string, unknown> = {}): string {
  const Block = block.render as (p: Record<string, unknown>) => ReactElement;
  const defaults = (block.defaultProps ?? {}) as Record<string, unknown>;
  return renderToStaticMarkup(<Block {...defaults} {...props} />);
}

/**
 * `block`'s markup given *only* `props` — no defaults merged in.
 *
 * This is what the viewer actually does. `defaultProps` fills a block's fields
 * when a writer drops it on the canvas; it is not applied again at render time,
 * so a document saved before a field existed reaches `render` with that prop
 * `undefined`. Back-compatibility assertions have to use this one — through
 * `renderBlock` the default quietly supplies the very prop the test is claiming
 * is absent, and the test passes without proving anything.
 */
export function renderStored(block: Renderable, props: Record<string, unknown>): string {
  const Block = block.render as (p: Record<string, unknown>) => ReactElement;
  return renderToStaticMarkup(<Block {...props} />);
}
