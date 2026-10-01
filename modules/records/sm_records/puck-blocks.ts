/**
 * Registers this module's Puck blocks. Importing this file is the whole API —
 * the host globs every module's `puck-blocks.ts` eagerly at app start, before
 * anything renders. Mirrors `news`'s own `puck-blocks.ts`, named in the
 * design doc (§16) as the seam to copy for this exact integration.
 *
 * This is what keeps the dependency pointing one way: records knows about
 * pagebuilder, and pagebuilder knows nothing about records.
 */

import { registerPuckBlocks } from '@simple-module-py/pagebuilder/pagebuilder/components/blockRegistry';

import { RecordsListBlock } from './components/widget/RecordsListBlock';

registerPuckBlocks({
  blocks: { RecordsList: RecordsListBlock },
  category: { key: 'data', title: 'Data' },
  // Page-only: a live records table in the site header or footer would
  // repeat, unfiltered, on every page of the site.
});
