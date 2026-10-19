/**
 * Registers the news feed block into pagebuilder's palette — where pagebuilder
 * is there to have one.
 *
 * This file, and the `NewsFeed` component it pulls in, are the *only* two
 * places in this module's frontend allowed to import `@simple-module-py/
 * pagebuilder`. Everything else — the admin list, the editors, the public
 * article viewer — has to work on a host that never installed it, which is what
 * the split was for. `test_module.py` guards the equivalent rule on the Python
 * side; here the rule is short enough to keep by reading.
 *
 * This is deliberately *not* named `puck-blocks.ts`. The host globs every
 * module's `puck-blocks.ts` eagerly, so a file by that name is built into every
 * host, and a bundler cannot make a static import conditional — a host without
 * pagebuilder would fail to resolve the import below. Instead pagebuilder's own
 * `puck-blocks.ts` globs every sibling package's `pagebuilder-blocks.ts`. The file
 * is therefore reachable only from a build that includes pagebuilder; on any
 * other host it is simply never imported (a glob that matches nothing is not an
 * error), and no block-glob exclusion is needed.
 *
 * The registration itself is guarded because it runs eagerly at app start, and
 * a throw here would take down the whole bundle's init rather than quietly
 * leaving one block unregistered.
 *
 * `@simple-module-py/pagebuilder` is an *optional* peer dependency, so npm does
 * not demand it of a host that never installs it.
 */

import { registerPuckBlocks } from '@simple-module-py/pagebuilder/pagebuilder/components/blockRegistry';

import { NewsFeedBlock } from './components/NewsFeed';
import { keys } from './utils/i18n';

try {
  registerPuckBlocks({
    blocks: { NewsFeed: NewsFeedBlock },
    category: { key: 'feeds', title: keys.news.feed.palette_group },
    // Page-only: a news grid in the site header or footer would repeat on
    // every page of the site.
  });
} catch (error) {
  // Registering twice throws by design — the registry refuses a name that is
  // already taken, because two blocks sharing one would each render the
  // other's saved data. In a hot-reloading dev server that is a re-run of this
  // module rather than a real collision, and it must not blank the editor.
  console.warn('[news] NewsFeed block not registered:', error);
}
