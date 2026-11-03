/**
 * A document whose every block has an id, and no id twice (#266).
 *
 * Puck's `<Render>` keys each block by `props.id`. The canvas mints one for
 * every block it creates, but a body written through the API — every e2e seed,
 * any script or import — need not carry one, and nothing on the server adds
 * it. Without this the reader's page handed React a list of blocks keyed
 * `undefined` (or the same id twice) and logged "Each child in a list should
 * have a unique key".
 *
 * A missing or repeated id is filled from the block's position. That is the
 * one place an index is the right key: the public page draws a stored document
 * once and never reorders it, so the position *is* stable for its lifetime.
 * An id the writer's document already carries is kept — the outline finds a
 * heading's anchor by it — and the first holder of a repeated id keeps it.
 *
 * Pure and copy-on-write: the stored document is the server's prop, and only
 * the blocks that needed an id are new objects.
 */

interface Block {
  type?: unknown;
  props?: Record<string, unknown>;
}

export function withBlockIds<T extends { content?: unknown }>(data: T): T {
  if (!Array.isArray(data?.content)) return data;
  const blocks = data.content as Block[];
  const used = new Set<string>();
  for (const block of blocks) {
    const id = block?.props?.id;
    if (typeof id === 'string' && id) used.add(id);
  }
  const seen = new Set<string>();
  let changed = false;
  const content = blocks.map((block, index) => {
    const id = block?.props?.id;
    if (typeof id === 'string' && id && !seen.has(id)) {
      seen.add(id);
      return block;
    }
    let fresh = `block-${index}`;
    let suffix = 2;
    while (used.has(fresh)) {
      fresh = `block-${index}-${suffix}`;
      suffix += 1;
    }
    used.add(fresh);
    seen.add(fresh);
    changed = true;
    return { ...block, props: { ...(block?.props ?? {}), id: fresh } };
  });
  return changed ? { ...data, content } : data;
}
