/**
 * Registers the `ImageGallery` block in pagebuilder's palette when pagebuilder
 * is installed. Images knows about pagebuilder; pagebuilder knows nothing about
 * images.
 *
 * Deliberately named `pagebuilder-blocks.ts`, as news' and records' are: the
 * host eagerly globs every module's `puck-blocks.ts`, so that name would make a
 * host without pagebuilder resolve the static import below and fail to build.
 * Pagebuilder's own `puck-blocks.ts` globs sibling packages'
 * `pagebuilder-blocks.ts` instead (since 0.0.12 - the floor on the `pagebuilder`
 * extra), so only hosts with pagebuilder import this file.
 * `@simple-module-py/pagebuilder` is an optional peer dependency.
 */

import { registerPuckBlocks } from '@simple-module-py/pagebuilder/pagebuilder/components/blockRegistry';

import { ImageGalleryBlock } from './components/block/ImageGalleryBlock';
import { keys } from './utils/i18n';

try {
  registerPuckBlocks({
    blocks: { ImageGallery: ImageGalleryBlock },
    // A catalogue key, resolved by pagebuilder's localizeConfig at render.
    category: { key: 'images', title: keys.images.block.palette_group },
    // Page-only: a gallery in the site header or footer would repeat on every page.
  });
} catch (error) {
  // Registering twice throws by design (a name already taken); in a
  // hot-reloading dev server that is a re-run of this module, and it must not
  // blank the editor.
  console.warn('[images] ImageGallery block not registered:', error);
}
