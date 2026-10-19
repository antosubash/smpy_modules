/**
 * Loads the Puck blocks that other modules contribute to this one.
 *
 * Dependency direction: a module that adds a block (news' `NewsFeed`) knows
 * about pagebuilder, so pagebuilder must not know about it. A contributing
 * module ships `<pkg>/pagebuilder-blocks.ts`, which imports `registerPuckBlocks`
 * from here and registers; this file globs them in. Because the contributor's
 * file is imported only from *this* one, a host that does not install
 * pagebuilder never builds it — no import of `@simple-module-py/pagebuilder`
 * is left dangling, and the host needs no hand-written exclusion.
 *
 * The host imports this file (it matches its `puck-blocks.ts` glob) eagerly at
 * app start, which is what guarantees the registry is populated before the
 * first render.
 *
 * Two levels up from this directory is the tree that holds every installed
 * module package (`modules/` in a workspace checkout, the Python `lib/` dir that
 * contains `site-packages/` in a wheel install), so `*` / `*` is
 * `<dist>/<package>` in both. A glob that matches nothing is not an error.
 */
import.meta.glob('../../*/*/pagebuilder-blocks.ts', { eager: true });
