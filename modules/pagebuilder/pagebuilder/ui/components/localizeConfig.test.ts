import { describe, expect, it } from 'vitest';

import { localizeConfig, localizeFields, localizeViewports } from './localizeConfig';

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

describe('localizeFields', () => {
  const fields = {
    heading: { type: 'text', label: 'events.blocks.upcoming.heading' },
    layout: {
      type: 'select',
      label: 'events.blocks.upcoming.layout',
      options: [
        { label: 'events.blocks.upcoming.layout_list', value: 'list' },
        { label: 'events.blocks.upcoming.layout_cards', value: 'cards' },
      ],
    },
    calendars: {
      type: 'array',
      label: 'events.blocks.upcoming.calendars',
      arrayFields: {
        slug: {
          type: 'select',
          label: 'events.blocks.fields.calendar',
          options: [{ label: 'A calendar name', value: 'a' }],
        },
        nested: {
          type: 'object',
          label: 'events.blocks.fields.group',
          objectFields: {
            inner: { type: 'text', label: 'events.blocks.fields.inner' },
          },
        },
      },
    },
  };

  it('translates labels, option labels and nested array and object field labels', () => {
    const out = localizeFields(fields, shout) as typeof fields;
    expect(out.heading.label).toBe('T(events.blocks.upcoming.heading)');
    expect(out.layout.options.map((o) => o.label)).toEqual([
      'T(events.blocks.upcoming.layout_list)',
      'T(events.blocks.upcoming.layout_cards)',
    ]);
    expect(out.calendars.label).toBe('T(events.blocks.upcoming.calendars)');
    expect(out.calendars.arrayFields.slug.label).toBe('T(events.blocks.fields.calendar)');
    expect(out.calendars.arrayFields.nested.objectFields.inner.label).toBe(
      'T(events.blocks.fields.inner)',
    );
  });

  it('leaves values and non-label strings alone', () => {
    const out = localizeFields(fields, shout) as typeof fields;
    expect(out.layout.options.map((o) => o.value)).toEqual(['list', 'cards']);
    expect(out.heading.type).toBe('text');
    expect(out.calendars.arrayFields.slug.type).toBe('select');
  });

  it('does not mutate its input', () => {
    const before = JSON.stringify(fields);
    localizeFields(fields, shout);
    expect(JSON.stringify(fields)).toBe(before);
  });

  it('leaves an option label that is already text as text', () => {
    const echo = (key: string) => key;
    const out = localizeFields(fields, echo) as typeof fields;
    expect(out.calendars.arrayFields.slug.options[0].label).toBe('A calendar name');
  });
});
