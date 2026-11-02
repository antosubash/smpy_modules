import { describe, expect, it } from 'vitest';

describe('pagebuilder-blocks', () => {
  it('registers ImageGallery and ImageStats in its own palette group, by catalogue key', async () => {
    const { registeredBlocks } = await import(
      '@simple-module-py/pagebuilder/pagebuilder/components/blockRegistry'
    );
    await import('../../pagebuilder-blocks');
    const mine = registeredBlocks().find((r) => 'ImageGallery' in r.blocks);
    expect(mine?.blocks).toHaveProperty('ImageStats');
    expect(mine?.category).toEqual({ key: 'images', title: 'images.block.palette_group' });
    expect(mine?.layout).toBeFalsy();
  });
});
