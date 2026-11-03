import { describe, expect, it } from 'vitest';

import { localizeConfig, localizeViewports } from './localizeConfig';

/**
 * The half of the i18n mechanism `tsc` cannot check.
 *
 * A block config holds catalogue keys, and Puck shows whatever the object
 * carries — so a label this misses is not a type error, it is a dotted key on
 * screen. The nested cases are the ones that were missed first: an `array`
 * field's own label resolves while the labels inside its rows do not, which
 * only shows up once someone expands a row.
 */

const shout = (key: string) => `T(${key})`;

describe('localizeConfig', () => {
  it('resolves labels at every depth a field can nest', () => {
    const config = {
      categories: { sections: { title: 'cat.title' }, plain: { visible: false } },
      components: {
        Hero: {
          label: 'hero.label',
          fields: {
            title: { type: 'text', label: 'hero.title' },
            align: {
              type: 'select',
              label: 'hero.align',
              options: [{ label: 'hero.align_left', value: 'left' }, { value: 'right' }],
            },
            items: {
              type: 'array',
              label: 'hero.items',
              arrayFields: {
                caption: { type: 'text', label: 'hero.items_caption' },
                size: {
                  type: 'select',
                  label: 'hero.items_size',
                  options: [{ label: 'hero.items_size_lg', value: 'lg' }],
                },
              },
            },
            link: {
              type: 'object',
              label: 'hero.link',
              objectFields: { href: { type: 'text', label: 'hero.link_href' } },
            },
          },
        },
      },
      root: { fields: { width: { type: 'radio', label: 'root.width' } } },
    };

    const out = localizeConfig(config, shout);
    const hero = out.components.Hero;

    expect(out.categories.sections.title).toBe('T(cat.title)');
    expect(hero.label).toBe('T(hero.label)');
    expect(hero.fields.title.label).toBe('T(hero.title)');
    expect(hero.fields.align.options[0].label).toBe('T(hero.align_left)');
    expect(hero.fields.items.label).toBe('T(hero.items)');
    expect(hero.fields.items.arrayFields.caption.label).toBe('T(hero.items_caption)');
    expect(hero.fields.items.arrayFields.size.options[0].label).toBe('T(hero.items_size_lg)');
    expect(hero.fields.link.objectFields.href.label).toBe('T(hero.link_href)');
    expect(out.root.fields.width.label).toBe('T(root.width)');
  });

  it('leaves defaultProps alone', () => {
    // Seed *content*, saved into the document the moment a block is inserted.
    // Translating it would rewrite what a visitor is served in whatever
    // language the author happened to be working in.
    const config = {
      components: { Text: { label: 'text.label', defaultProps: { body: 'Edit me' } } },
    };
    expect(localizeConfig(config, shout).components.Text.defaultProps).toEqual({ body: 'Edit me' });
  });

  it('passes an option or category through untouched when it has no label', () => {
    const config = {
      categories: { plain: { visible: false } },
      components: { Spacer: { fields: { size: { type: 'number' } } } },
    };
    const out = localizeConfig(config, shout);
    expect(out.categories.plain).toEqual({ visible: false });
    expect(out.components.Spacer.fields.size).toEqual({ type: 'number' });
  });
});

describe('localizeViewports', () => {
  it('resolves the switcher labels and keeps the rest of each entry', () => {
    const out = localizeViewports([{ width: 360, label: 'vp.mobile' }, { width: 1280 }], shout);
    expect(out).toEqual([{ width: 360, label: 'T(vp.mobile)' }, { width: 1280 }]);
  });
});
