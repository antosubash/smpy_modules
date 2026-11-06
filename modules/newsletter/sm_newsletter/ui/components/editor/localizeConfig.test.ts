import { describe, expect, it } from 'vitest';

import { localizeConfig } from './localizeConfig';
import { buildConfig } from './puckConfig';

const shout = (key: string) => `T(${key})`;

type Labelled = { label?: string; options?: { label?: string }[] | Record<string, unknown> };

describe('localizeConfig', () => {
  it('resolves labels to strings', () => {
    const out = localizeConfig(buildConfig({ news: true, pagebuilder: true }), shout);
    const cats = out.categories as Record<string, { title?: string }>;
    expect(cats.content.title).toBe('T(newsletter.blocks.categories.content)');
    expect(cats.cards.title).toBe('T(newsletter.blocks.categories.cards)');

    const heading = out.components.Heading as { label?: string; fields: Record<string, Labelled> };
    expect(heading.label).toBe('T(newsletter.blocks.heading.label)');
    expect(heading.fields.text.label).toBe('T(newsletter.blocks.heading.text)');
    expect((heading.fields.level.options as { label?: string }[])[0].label).toBe(
      'T(newsletter.blocks.heading.level_1)',
    );

    // Every label left in the config is resolved: none is still a bare key.
    for (const component of Object.values(out.components) as {
      label?: string;
      fields?: Record<string, Labelled>;
    }[]) {
      expect(component.label).toMatch(/^T\(newsletter\./);
      for (const field of Object.values(component.fields ?? {})) {
        if (field.label) expect(field.label).toMatch(/^T\(/);
        // A richtext field's `options` is its extension switches, not choices.
        if (!Array.isArray(field.options)) continue;
        for (const option of field.options) expect(option.label).toMatch(/^T\(/);
      }
    }
  });

  it("leaves a richtext field's extension options alone", () => {
    const out = localizeConfig(buildConfig({ news: false, pagebuilder: false }), shout);
    const html = (out.components.RichText as { fields: Record<string, Labelled> }).fields.html;
    expect(html.label).toBe('T(newsletter.blocks.rich_text.html)');
    expect(html.options).toMatchObject({ heading: false, codeBlock: false });
  });

  it('recurses into object and array fields and leaves defaultProps alone', () => {
    const config = {
      components: {
        X: {
          label: 'x.label',
          defaultProps: { text: 'Seed' },
          fields: {
            list: { type: 'array', label: 'x.list', arrayFields: { a: { label: 'x.a' } } },
            obj: { type: 'object', label: 'x.obj', objectFields: { b: { label: 'x.b' } } },
          },
        },
      },
    };
    const out = localizeConfig(config, shout).components.X;
    expect(out.fields.list.arrayFields.a.label).toBe('T(x.a)');
    expect(out.fields.obj.objectFields.b.label).toBe('T(x.b)');
    expect(out.defaultProps).toEqual({ text: 'Seed' });
  });
});
