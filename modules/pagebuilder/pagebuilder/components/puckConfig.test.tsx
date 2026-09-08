import { beforeEach, describe, expect, it } from 'vitest';

import { translate } from '../utils/i18n';
import { type AnyBlock, registerPuckBlocks, resetBlockRegistry } from './blockRegistry';
import { getLayoutPuckConfig } from './layoutPuckConfig';
import { localizeConfig } from './localizeConfig';
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

  it('localizes a registered block against another module’s namespace', () => {
    // The reason a contributed block can hold catalogue keys at all. The host
    // merges every module's catalogue into one flat table and i18next is
    // configured with `keySeparator: false`, so `news.…` is a whole key rather
    // than a path into a namespace this module would have to know about —
    // `localizeConfig` walks the *assembled* config and resolves it with
    // pagebuilder's own `t`. A real news key, because a made-up one would
    // resolve to itself and prove nothing.
    registerPuckBlocks({
      blocks: { Widget: { ...stub, label: 'news.list.title' } as AnyBlock },
      category: { key: 'feeds', title: 'news.list.title' },
    });
    const config = localizeConfig(getPuckConfig(), translate);
    // Through a structural view: the config's static type names pagebuilder's
    // own 56 blocks, and a contributed one is only ever known at runtime —
    // which is the whole point of the registry.
    const components = config.components as unknown as Record<string, { label?: string }>;
    expect(components.Widget.label).toBe('News');
    expect(config.categories?.feeds?.title).toBe('News');
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
