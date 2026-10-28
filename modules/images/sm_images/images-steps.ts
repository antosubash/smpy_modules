/**
 * Loads the result views that other modules contribute to images.
 *
 * The same shape as pagebuilder's `puck-blocks.ts`: a plugin ships
 * `<pkg>/images-steps.ts`, which calls `registerResultView` from
 * `@simple-module-py/images`; this file globs them in, so images never imports
 * a plugin and a host without the plugin builds nothing dangling.
 *
 * Imported for its side effect by the console page that renders results
 * (`pages/Image.tsx`), so the registry is filled before the first render. The
 * glob skips this file itself. A glob that matches nothing is not an error.
 */
import.meta.glob('../../*/*/images-steps.ts', { eager: true });
