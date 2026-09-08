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
 * Puck also passes `id` and a `puck` bag alongside the authored props, and
 * three blocks now read them: `Heading` and `Contents` take the document's
 * outline out of `puck.metadata`, and `Related` takes the current slug. Those
 * go in through `props` like anything else — the bag has no defaults to merge,
 * so there is nothing for this helper to supply, and a test that wants one
 * writes the shape it is asserting about.
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
