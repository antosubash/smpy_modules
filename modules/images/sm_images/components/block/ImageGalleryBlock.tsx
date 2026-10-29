/**
 * `ImageGallery` Puck block: a public collection's thumbnails on a page.
 *
 * The collection picker is admin-only (`resolveFields` reads the session-gated
 * collection list, and only the editor calls it); the rendered block never
 * does. `<Render>` on the public page reads the anonymous twin only, so a
 * collection made private after the page was published simply stops showing
 * (the twin answers 404 and the block renders nothing).
 *
 * Labels are catalogue keys, as in news' blocks: the block is a module-scope
 * constant, so pagebuilder's `localizeConfig` resolves them when the editor
 * mounts. `resolveFields` runs later, per edit, so it translates directly.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { listCollections } from '../../utils/api';
import { keys, type Translate, translate } from '../../utils/i18n';
import type { Collection, Page } from '../../utils/types';
import { PublicGallery, type TileSize } from '../public/PublicGallery';

export interface ImageGalleryProps {
  /** The slug of a public collection ('' until one is chosen). */
  collection: string;
  size: TileSize;
  count: number;
}

export const COUNT_MIN = 1;
export const COUNT_MAX = 48;
export const COUNT_DEFAULT = 8;
const MAX_PICKER_PAGES = 100;
const SIZES: TileSize[] = ['small', 'medium', 'large'];

/** Stored props may predate the editor's constraints, and a fractional or
 *  out-of-range count is a 422 from the list route. */
export function clampCount(value: unknown): number {
  const n = Math.trunc(Number(value));
  if (!Number.isFinite(n)) return COUNT_DEFAULT;
  return Math.min(COUNT_MAX, Math.max(COUNT_MIN, n));
}

function buildFields(tr: Translate, collections: { label: string; value: string }[]) {
  return {
    collection: {
      type: 'select' as const,
      label: tr(keys.images.block.collection),
      options: [{ label: tr(keys.images.block.choose), value: '' }, ...collections],
    },
    size: {
      type: 'select' as const,
      label: tr(keys.images.block.size),
      options: [
        { label: tr(keys.images.block.size_small), value: 'small' },
        { label: tr(keys.images.block.size_medium), value: 'medium' },
        { label: tr(keys.images.block.size_large), value: 'large' },
      ],
    },
    count: {
      type: 'number' as const,
      label: tr(keys.images.block.count),
      min: COUNT_MIN,
      max: COUNT_MAX,
    },
  };
}

/** Public collections only: a gallery of a private one would render nothing for
 *  a visitor, and offering it would be a trap. Empty when the editor is
 *  offline or signed out, which must not break the editor. */
async function publicCollections() {
  const found: { label: string; value: string }[] = [];
  try {
    let cursor: string | null = null;
    // Bounded: a cursor that never ends must not hang the editor.
    for (let i = 0; i < MAX_PICKER_PAGES; i++) {
      const page: Page<Collection> = await listCollections('public', cursor);
      for (const c of page.items) {
        if (c.visibility === 'public') found.push({ label: c.name, value: c.slug });
      }
      cursor = page.next_cursor;
      if (!cursor) break;
    }
  } catch {
    // Keep what loaded: a later page failing must not empty the picker.
  }
  return found;
}

export function ImageGalleryRender({ collection, size, count }: ImageGalleryProps) {
  // Nothing until a collection is chosen: an empty frame reads as a broken block.
  if (!collection) return <></>;
  return (
    <PublicGallery
      slug={collection}
      name={collection}
      size={SIZES.includes(size) ? size : 'medium'}
      count={clampCount(count)}
    />
  );
}

export const ImageGalleryBlock: ComponentConfig<ImageGalleryProps> = {
  label: keys.images.block.label,
  // Static labels are keys; `resolveFields` below replaces them with text.
  fields: buildFields((key) => key, []),
  defaultProps: { collection: '', size: 'medium', count: COUNT_DEFAULT },
  resolveFields: async () => buildFields(translate, await publicCollections()),
  resolveData: ({ props }, { trigger }) =>
    trigger === 'load' ? { props: { ...props, count: clampCount(props.count) } } : { props },
  render: ImageGalleryRender,
};
