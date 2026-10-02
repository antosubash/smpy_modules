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
 * The registration itself is guarded because the neighbour may be absent at
 * *runtime*: the host globs every module's `puck-blocks.ts` eagerly at app
 * start, and a throw here would take down the whole bundle's init rather than
 * quietly leaving one block unregistered.
 *
 * A bundler cannot make a static import conditional, so on a host that installs
 * neither the npm package nor the wheel this file has nothing to resolve. That
 * is why `@simple-module-py/pagebuilder` is an *optional* peer dependency: npm
 * will not demand it, and a host without it simply does not ship this block.
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
