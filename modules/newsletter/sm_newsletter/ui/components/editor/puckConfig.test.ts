import { describe, expect, it } from 'vitest';

import { buildConfig } from './puckConfig';

/** Ruling C9: every block is always *defined*, so a card already in the body
 *  renders and can be deleted; only the palette depends on the capabilities. */

const ALL = [
  'Heading',
  'RichText',
  'Image',
  'Button',
  'Divider',
  'Spacer',
  'ArticleCard',
  'PageCard',
];

type Caps = { news: boolean; pagebuilder: boolean };

function categories(caps: Caps) {
  const config = buildConfig(caps);
  return config.categories as Record<string, { components?: string[]; visible?: boolean }>;
}

describe('buildConfig', () => {
  it('defines all eight blocks always', () => {
    for (const news of [true, false]) {
      for (const pagebuilder of [true, false]) {
        const config = buildConfig({ news, pagebuilder });
        expect(Object.keys(config.components).sort()).toEqual([...ALL].sort());
      }
    }
  });

  it('puts content and layout blocks in their categories and hides "other"', () => {
    const cats = categories({ news: true, pagebuilder: true });
    expect(cats.content.components).toEqual(['Heading', 'RichText', 'Image', 'Button']);
    expect(cats.layout.components).toEqual(['Divider', 'Spacer']);
    expect(cats.other).toEqual({ visible: false });
  });

  it('lists both cards when both integrations are available', () => {
    const cats = categories({ news: true, pagebuilder: true });
    expect(cats.cards.components).toEqual(['ArticleCard', 'PageCard']);
    expect(cats.cards.visible).not.toBe(false);
    expect(cats.hidden).toEqual({ components: [], visible: false });
  });

  it('hides ArticleCard when news is absent', () => {
    const cats = categories({ news: false, pagebuilder: true });
    expect(cats.cards.components).toEqual(['PageCard']);
    expect(cats.hidden).toEqual({ components: ['ArticleCard'], visible: false });
  });

  it('hides PageCard when pagebuilder is absent', () => {
    const cats = categories({ news: true, pagebuilder: false });
    expect(cats.cards.components).toEqual(['ArticleCard']);
    expect(cats.hidden).toEqual({ components: ['PageCard'], visible: false });
  });

  it('hides the cards category when neither integration is available', () => {
    const cats = categories({ news: false, pagebuilder: false });
    expect(cats.cards.visible).toBe(false);
    expect(cats.cards.components).toEqual([]);
    expect(cats.hidden).toEqual({ components: ['ArticleCard', 'PageCard'], visible: false });
  });

  it('no slot or dropzone fields', () => {
    const config = buildConfig({ news: true, pagebuilder: true });
    const blocks = { ...config.components, root: config.root ?? {} } as Record<
      string,
      { fields?: Record<string, { type: string }> }
    >;
    for (const [name, block] of Object.entries(blocks)) {
      for (const field of Object.values(block.fields ?? {})) {
        expect(field.type, name).not.toBe('slot');
      }
    }
    expect(Object.keys(config.root?.fields ?? {})).toEqual([]);
  });

  it('uses Puck richtext for RichText, without formatting the sanitiser drops', () => {
    const config = buildConfig({ news: false, pagebuilder: false });
    const field = (
      config.components.RichText.fields as unknown as Record<string, Record<string, unknown>>
    ).html;
    expect(field.type).toBe('richtext');
    expect(field.options).toMatchObject({
      heading: false,
      code: false,
      codeBlock: false,
      horizontalRule: false,
      textAlign: false,
    });
  });
});
