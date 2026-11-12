import * as surface from '@simple-module-py/pagebuilder';
import { describe, expect, it } from 'vitest';

import * as registry from './blockRegistry';

// What news, records and images import from `@simple-module-py/pagebuilder`
// (#337). Dropping one breaks a sibling's build, not pagebuilder's own.
describe('the package entry', () => {
  it('exports exactly what sibling modules use', () => {
    // Pinned in full, so growing the public API is a reviewed change.
    expect(Object.keys(surface).sort()).toEqual([
      'ArticleCardsGrid',
      'Section',
      'StatsView',
      'createImageField',
      'isSafeHref',
      'lazyBlock',
      'mediaLibraryAdapter',
      'registerPuckBlocks',
      'registeredBlocks',
      'safeHref',
    ]);
  });

  it('shares the registry the editor reads', () => {
    // Resolved through the package's `exports`, the entry must land on the same
    // module instance as pagebuilder's own relative import, or a sibling would
    // register into a registry the editor never reads.
    expect(surface.registerPuckBlocks).toBe(registry.registerPuckBlocks);
  });
});
