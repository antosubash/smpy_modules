/**
 * Bring stored page data up to the shape the current Puck version expects.
 *
 * Every load path — editor, public page, layout header/footer — runs its data
 * through here before handing it to Puck, so a payload written by an older
 * build can't reach `<Puck>`/`<Render>` in a shape they no longer understand.
 */

import { type Config, type Content, type Data, migrate } from '@puckeditor/core';

/**
 * Pre-slots payloads keep nested content in a top-level `zones` map keyed
 * `"<componentId>:<zoneName>"`, and the very oldest ones store root props
 * directly on `root` rather than under `root.props`. Neither key is in the
 * modern `Data` type, so they're only visible through this widening.
 */
type LegacyData = Data & {
  zones?: Record<string, unknown>;
  root?: Record<string, unknown>;
};

function hasLegacyShape(data: Data): boolean {
  const legacy = data as LegacyData;
  if (legacy.zones && Object.keys(legacy.zones).length > 0) return true;
  const root = legacy.root;
  // `!root.props` rather than `!("props" in root)`, matching Puck's own check.
  // A stored `root: { props: null, … }` has the key but no usable value, and
  // treating it as modern would hand `<Render>` a null `root.props` instead of
  // letting Puck normalise it.
  return !!root && !root.props && Object.keys(root).length > 0;
}

/** A `Columns` column, pre- and post-migration. */
type ColumnItem = { width?: number; content?: Content };

/**
 * Fold a pre-slots `Columns` block's zones into its array slots.
 *
 * Puck's own zone→slot conversion only matches a zone against a *top-level*
 * slot field of the same name. `Columns` can't have one: the column count is
 * author-controlled, so its slot lives at `columns[i].content` inside an array
 * field. `migrateDynamicZonesForComponent` is the escape hatch for exactly
 * that shape — Puck hands us the block's props plus its zones (keyed by bare
 * prop name, `col-0` / `col-1` / …) and takes whatever props we return.
 *
 * The zone index is authoritative, not the stored `columns` array: a page
 * saved after a column was removed can still carry a zone for it. Sizing the
 * result to cover both means such orphaned content reappears in a real column
 * instead of being silently dropped on migration.
 *
 * Anything left over is appended to the last column rather than abandoned.
 * Puck deletes *every* zone it grouped for this block once we return, whether
 * or not we read it — so a zone this function doesn't claim is not left behind
 * to raise the "no slot exists" error, it simply stops existing. Only
 * `col-<int>` was ever emitted here, so the sweep should find nothing; it costs
 * one pass and removes the one path where losing author content would be
 * silent, which is the failure this function exists to prevent.
 */
const COLUMN_ZONE = /^col-(\d+)$/;
/**
 * Ceiling on a column index taken from a *zone name*, which is the only input
 * here with no natural bound — `col-500000` would otherwise size the loop
 * below. It deliberately does not cap the stored `columns` array: that is real
 * author data, however long, and clamping it would trade an allocation worry
 * for silent content loss. An index past the ceiling isn't dropped either; it
 * falls through to the unclaimed sweep.
 */
const MAX_ZONE_INDEX = 64;

function migrateColumnsZones(
  props: { id: string } & Record<string, unknown>,
  zones: Record<string, Content>,
): { id: string } & Record<string, unknown> {
  const stored = Array.isArray(props.columns) ? (props.columns as ColumnItem[]) : [];
  const indexed = new Map<number, Content>();
  const unclaimed: Content = [];
  for (const [name, blocks] of Object.entries(zones)) {
    const match = COLUMN_ZONE.exec(name);
    const index = match ? Number(match[1]) : -1;
    if (index >= 0 && index < MAX_ZONE_INDEX) indexed.set(index, blocks);
    else if (Array.isArray(blocks)) unclaimed.push(...blocks);
  }

  const count = Math.max(stored.length, ...[...indexed.keys()].map((n) => n + 1), 0);

  const columns: ColumnItem[] = [];
  for (let i = 0; i < count; i += 1) {
    columns.push({
      width: stored[i]?.width ?? 1,
      content: indexed.get(i) ?? stored[i]?.content ?? [],
    });
  }

  if (unclaimed.length > 0) {
    if (columns.length === 0) columns.push({ width: 1, content: [] });
    const last = columns[columns.length - 1];
    last.content = [...(last.content ?? []), ...unclaimed];
    console.warn(
      `[pagebuilder] ${unclaimed.length} block(s) from an unrecognised Columns zone were ` +
        `appended to the last column of "${props.id}" rather than dropped.`,
    );
  }
  return { ...props, columns };
}

/**
 * Run Puck's `migrate()`, but only when the payload actually carries a legacy
 * shape.
 *
 * The version check is not just an optimisation. `migrate()` walks the tree
 * twice and logs "Migrating DropZones..." unconditionally, and the public
 * viewer renders on every request — so calling it for the modern payloads that
 * are the overwhelming majority would put two needless walks and a console
 * line on the hot path.
 *
 * `migrate()` still throws on a zone nothing claims — a zone whose owning
 * component is no longer in the tree, say. Returning the original data there
 * keeps the rest of the page rendering: the blast radius stays at the one bad
 * zone rather than the whole document.
 */
export function migrateContent<T extends Data>(data: T, config: Config): T {
  if (!hasLegacyShape(data)) return data;
  try {
    // Generic because this is shape-preserving: the same document comes back,
    // only reshaped internally. `migrate()` is declared against the loose
    // `Data`, so the narrowing it can't express is asserted once here rather
    // than at each of the four call sites.
    return migrate(data, config, {
      migrateDynamicZonesForComponent: { Columns: migrateColumnsZones },
    }) as T;
  } catch (err) {
    console.error('[pagebuilder] Could not migrate legacy content; rendering as-is:', err);
    return data;
  }
}
