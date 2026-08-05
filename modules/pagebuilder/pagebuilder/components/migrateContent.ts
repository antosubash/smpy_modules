/**
 * Bring stored page data up to the shape the current Puck version expects.
 *
 * Every load path — editor, public page, layout header/footer — runs its data
 * through here before handing it to Puck, so a payload written by an older
 * build can't reach `<Puck>`/`<Render>` in a shape they no longer understand.
 */

import { type Config, type Data, migrate } from '@puckeditor/core';

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
  return !!root && !('props' in root) && Object.keys(root).length > 0;
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
 * `migrate()` throws on a zone it can't convert, and today that is *every*
 * populated zones map we could be handed: it only converts a zone into a slot
 * field of the same name, and no component in either config declares one —
 * `Columns`, our only nesting block, still renders `<DropZone zone="col-N">`.
 * So the catch below is the live path, not a defensive corner. Returning the
 * original data keeps the legacy DropZone rendering path working, which is
 * what those pages were relying on anyway.
 *
 * Porting `Columns` to slot fields is what turns the success path on; until
 * then this function's job for zones payloads is purely to contain the throw.
 */
export function migrateContent(data: Data, config: Config): Data {
  if (!hasLegacyShape(data)) return data;
  try {
    return migrate(data, config);
  } catch (err) {
    console.error('[pagebuilder] Could not migrate legacy content; rendering as-is:', err);
    return data;
  }
}
