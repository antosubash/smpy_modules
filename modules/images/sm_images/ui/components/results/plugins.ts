/**
 * Loads the result views that other modules contribute to images.
 *
 * The same shape as pagebuilder's `puck-blocks.ts`: a plugin ships
 * `<pkg>/images-steps.ts`, which calls `registerResultView` from
 * `@simple-module-py/images`; this file globs them in, so images never imports
 * a plugin and a host without the plugin builds nothing dangling.
 *
 * Imported for its side effect by the component that renders results
 * (`components/results/ResultView.tsx`), so the registry is filled before the first render.
 * Images ships no `images-steps.ts` of its own. A glob that matches nothing is
 * not an error.
 */
import.meta.glob('../../../../../*/*/images-steps.ts', { eager: true });
