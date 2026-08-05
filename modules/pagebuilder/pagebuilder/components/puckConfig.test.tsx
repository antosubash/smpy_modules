import { beforeEach, describe, expect, it } from 'vitest';

import { type AnyBlock, registerPuckBlocks, resetBlockRegistry } from './blockRegistry';
import { getLayoutPuckConfig } from './layoutPuckConfig';
import { getPuckConfig } from './puckConfig';

const stub = { render: () => null } as unknown as AnyBlock;

describe('getPuckConfig', () => {
  beforeEach(() => resetBlockRegistry());

  it('includes pagebuilder’s own blocks', () => {
    expect(Object.keys(getPuckConfig().components)).toContain('Heading');
  });

  it('includes a registered block', () => {
    registerPuckBlocks({ blocks: { Widget: stub } });
    expect(Object.keys(getPuckConfig().components)).toContain('Widget');
  });

  it('picks up a registration made after the first read', () => {
    // The whole reason the memo keys on the registry version. Caching on first
    // call would drop any block whose module loaded later.
    expect(Object.keys(getPuckConfig().components)).not.toContain('Late');
    registerPuckBlocks({ blocks: { Late: stub } });
    expect(Object.keys(getPuckConfig().components)).toContain('Late');
  });

  it('files a registered block under its category', () => {
    registerPuckBlocks({ blocks: { Widget: stub }, category: { key: 'feeds', title: 'Feeds' } });
    expect(getPuckConfig().categories?.feeds).toEqual({
      title: 'Feeds',
      components: ['Widget'],
    });
  });

  it('leaves pagebuilder’s own categories intact', () => {
    registerPuckBlocks({ blocks: { Widget: stub }, category: { key: 'feeds', title: 'Feeds' } });
    expect(getPuckConfig().categories?.sections?.components).toContain('Hero');
  });
});

describe('getLayoutPuckConfig', () => {
  beforeEach(() => resetBlockRegistry());

  it('offers the site chrome', () => {
    expect(Object.keys(getLayoutPuckConfig().components)).toEqual(
      expect.arrayContaining(['SiteHeader', 'SiteFooter']),
    );
  });

  it('drops Columns, which the slots have no room for', () => {
    expect(Object.keys(getLayoutPuckConfig().components)).not.toContain('Columns');
  });

  it('offers only the curated chrome palette, not the whole page catalogue', () => {
    // This used to be built subtractively — the page palette minus a couple of
    // names — so every block added to the page silently appeared here too.
    // When the catalogue went 20 → 56, the header/footer editor started
    // offering Leaderboard, Timeline and ~45 other page sections under Puck's
    // catch-all "Other" group. Site chrome is a deliberately small palette.
    const names = Object.keys(getLayoutPuckConfig().components);
    expect(names).toEqual(
      expect.arrayContaining(['SiteHeader', 'SiteFooter', 'Heading', 'Text', 'Image']),
    );
    expect(names).not.toContain('Leaderboard');
    expect(names).not.toContain('Timeline');
    expect(names).not.toContain('Newsletter');
    // Every built-in must be filed under a category, since an uncategorised
    // block is what lands in Puck's "Other" group. This holds for built-ins
    // only — the registry is empty here, and a module registering with
    // `layout: true` and no category still joins `components` by design.
    const categorised = Object.values(getLayoutPuckConfig().categories ?? {}).flatMap(
      (c) => c.components ?? [],
    );
    expect(names.filter((n) => !categorised.includes(n))).toEqual([]);
  });

  it('still renders every block that was offered here before the palette was curated', () => {
    // Puck renders nothing for a type its config doesn't know — no error, no
    // placeholder. A footer saved with a ContactForm back when the layout
    // palette was the whole page palette must not silently lose that section.
    //
    // The full list, not a sample: this is the set the site-layout editor
    // offered before the catalogue grew, so any one of them could be sitting in
    // a stored header or footer, and dropping any one is the same silent loss.
    const names = Object.keys(getLayoutPuckConfig().components);
    expect(names).toEqual(
      expect.arrayContaining([
        'PageHeader',
        'Hero',
        'EyebrowSection',
        'MediaObject',
        'CallToAction',
        'FeatureCards',
        'Faq',
        'Stats',
        'ArticleCards',
        'ContactCards',
        'ContactForm',
        'Tags',
      ]),
    );
    // ...but they are not offered: `_legacy` is `visible: false`.
    expect(getLayoutPuckConfig().categories?._legacy?.visible).toBe(false);
  });

  it('excludes a page-only registration', () => {
    // A news feed belongs on a page, not in the header or footer.
    registerPuckBlocks({ blocks: { Widget: stub } });
    expect(Object.keys(getLayoutPuckConfig().components)).not.toContain('Widget');
  });

  it('includes a registration that opts into the layout', () => {
    registerPuckBlocks({ blocks: { Banner: stub }, layout: true });
    expect(Object.keys(getLayoutPuckConfig().components)).toContain('Banner');
  });
});
