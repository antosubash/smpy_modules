/**
 * Registers this module's Puck blocks. Importing this file is the whole API —
 * the host globs every module's `puck-blocks.ts` eagerly at app start, before
 * anything renders.
 *
 * This is what keeps the dependency pointing one way: news knows about
 * pagebuilder, and pagebuilder knows nothing about news.
 */

import { registerPuckBlocks } from '@simple-module-py/pagebuilder/pagebuilder/components/blockRegistry';

import { NewsFeedBlock } from './components/NewsFeed';

registerPuckBlocks({
  blocks: { NewsFeed: NewsFeedBlock },
  category: { key: 'feeds', title: 'Feeds' },
  // Page-only: a news grid in the site header or footer would repeat on
  // every page of the site.
});
