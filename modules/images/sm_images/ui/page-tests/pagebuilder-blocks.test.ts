import { describe, expect, it } from 'vitest';

describe('pagebuilder-blocks', () => {
  it('registers ImageGallery and ImageStats in its own palette group, by catalogue key', async () => {
    const { registeredBlocks } = await import(
      '@simple-module-py/pagebuilder/pagebuilder/ui/components/blockRegistry'
    );
    await import('../../pagebuilder-blocks');
    // Each block has its own guarded registration, so a clash on one name
    // cannot leave the other unregistered.
    for (const name of ['ImageGallery', 'ImageStats']) {
      const mine = registeredBlocks().find((r) => name in r.blocks);
      expect(mine, name).toBeDefined();
      expect(mine?.category).toEqual({ key: 'images', title: 'images.block.palette_group' });
      expect(mine?.layout).toBeFalsy();
    }
  });
});
