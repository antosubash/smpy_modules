/**
 * What the editor checks before it autosaves a body.
 *
 * Puck inserts a block with its default props, and some blocks have no valid
 * default: an image without an address, a card nothing was chosen for, a
 * heading whose text was cleared. The server refuses the whole body for one of
 * those (422 `invalid_body`), so sending it on every keystroke would only show
 * an error while the writer is still filling the block in. Instead the body
 * waits until every block has its required fields (`content/blocks.py`).
 */

import type { Block } from './types';

function filled(value: unknown): boolean {
  return typeof value === 'string' && value.trim() !== '';
}

/** Whether `block` has every field `content/blocks.py` requires. */
export function isComplete(block: Block): boolean {
  const p = block.props;
  switch (block.type) {
    case 'Heading':
      return filled(p.text);
    case 'Image':
      return filled(p.src);
    case 'Button':
      return filled(p.label) && filled(p.href);
    case 'ArticleCard':
    case 'PageCard':
      return typeof p.source_id === 'number' && p.source_id > 0 && filled(p.url);
    default:
      return true;
  }
}

/** The body as the server takes it: an optional field left empty is omitted
 *  rather than sent as `""` (an image's link must be a valid link or absent),
 *  and a cleared number falls back to the server's default. */
export function normalizeBody(body: Block[]): Block[] {
  return body.map((block) => {
    if (block.type !== 'Image') return block;
    const props = { ...block.props };
    if (!filled(props.href)) delete props.href;
    if (typeof props.width !== 'number' || !Number.isFinite(props.width)) delete props.width;
    return { ...block, props };
  });
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value as Record<string, unknown>)
        .sort()
        .map((k) => [k, sortKeys((value as Record<string, unknown>)[k])]),
    );
  }
  return value;
}

/** A serialisation that ignores key order, for "is this the body the server
 *  holds?". Puck puts a new block's `id` last and the server puts it first, so
 *  plain `JSON.stringify` would call two identical bodies different. */
export function bodyKey(body: Block[]): string {
  return JSON.stringify(sortKeys(body));
}
