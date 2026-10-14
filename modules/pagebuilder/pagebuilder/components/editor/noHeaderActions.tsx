/**
 * Puck `overrides` that drop the header's own "Publish" (#59).
 *
 * Both editors have a toolbar that owns saving and publishing, so Puck's
 * button would be a second, duplicate control. The title, undo/redo and
 * sidebar toggles stay. Module scope so Puck sees a stable object rather than
 * a fresh one on every render.
 */
export const NO_HEADER_ACTIONS = { headerActions: () => <></> };
