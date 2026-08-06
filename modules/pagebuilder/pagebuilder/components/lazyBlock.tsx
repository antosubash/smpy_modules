/**
 * Register a Puck block whose render component loads on demand (issue #16).
 *
 * Block registration is eager by design — the host imports every module's
 * `puck-blocks.ts` before first render so the registry is populated when a
 * page reads the Puck config. But a registration that statically imports its
 * render component drags the component's whole dependency graph into the
 * entry chunk, on every page of the site. Measured on a consuming site, a
 * map block put maplibre-gl — 1 MB minified, 62% of the bundle — in front
 * of every visitor.
 *
 * `lazyBlock` keeps the cheap parts eager (fields, defaults, labels) and
 * loads the component the first time a page actually renders the block:
 *
 * ```tsx
 * registerPuckBlocks({
 *   blocks: {
 *     CanopyAtlasMap: lazyBlock(
 *       () => import('./components/CanopyAtlasMap').then((m) => m.CanopyAtlasMapEmbed),
 *       {
 *         label: 'Canopy Atlas map',
 *         fields: { height: { type: 'select', options: HEIGHTS } },
 *         defaultProps: { height: 'screen' },
 *       },
 *       (props) => <div className={heightClass[props.height]} aria-busy="true" />,
 *     ),
 *   },
 * });
 * ```
 */

import { type ComponentType, lazy, type ReactNode, Suspense } from 'react';

import type { AnyBlock } from './blockRegistry';

// Typed via AnyBlock rather than a precise ComponentConfig<P>: Puck's config
// generic carries constraints a pass-through helper cannot restate, and the
// registry these blocks land in erases the props type anyway.
// biome-ignore lint/suspicious/noExplicitAny: heterogeneous block props, same as AnyBlock
type AnyProps = Record<string, any>;

export function lazyBlock<P extends AnyProps>(
  load: () => Promise<ComponentType<P>>,
  config: Omit<AnyBlock, 'render'>,
  /** Rendered while the chunk downloads — size it like the block to avoid
   *  layout shift. Defaults to nothing. */
  fallback?: (props: P) => ReactNode,
): AnyBlock {
  const Lazy = lazy(async () => ({ default: await load() }));
  return {
    ...config,
    render: (props: AnyProps) => (
      <Suspense fallback={fallback ? fallback(props as P) : null}>
        <Lazy {...(props as P)} />
      </Suspense>
    ),
  };
}
