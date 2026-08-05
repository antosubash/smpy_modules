import { describe, expect, it } from 'vitest';

import { basePageConfig } from '../components/puckConfig';
import { applyTranslatedStrings, extractTranslatableStrings } from './index';

const config = basePageConfig as never;

const fixture = JSON.stringify({
  content: [
    { type: 'Heading', props: { id: 'h1', text: 'About us', level: 'h1', align: 'left' } },
    { type: 'Text', props: { id: 't1', text: 'Welcome to **us**', size: 'base', align: 'left' } },
    {
      type: 'FeatureCards',
      props: {
        id: 'f1',
        title: 'Features',
        items: [{ title: 'Fast', description: 'Very fast', href: '/a', iconUrl: '/i.png' }],
      },
    },
    { type: 'Image', props: { id: 'i1', src: '/pic.png', alt: 'A picture' } },
  ],
  root: { props: { title: 'The page', width: 'contained' } },
});

describe('extract / apply round trip', () => {
  it('takes the copy and leaves urls, ids and images alone', () => {
    const { strings } = extractTranslatableStrings(fixture, config);
    expect(strings).toContain('About us');
    expect(strings).toContain('Welcome to **us**');
    expect(strings).toContain('Features');
    expect(strings).toContain('Fast');
    expect(strings).toContain('Very fast');
    expect(strings).toContain('A picture');
    // `href` is denylisted by key; `src` and `iconUrl` are picker fields, so
    // they are `type: "custom"` and never text-typed to begin with.
    expect(strings).not.toContain('/a');
    expect(strings).not.toContain('/i.png');
    expect(strings).not.toContain('/pic.png');
  });

  it('reproduces the document when the strings are fed straight back', () => {
    const { strings, paths } = extractTranslatableStrings(fixture, config);
    expect(JSON.parse(applyTranslatedStrings(fixture, paths, strings))).toEqual(
      JSON.parse(fixture),
    );
  });

  it('writes each translation to the place it came from', () => {
    const { strings, paths } = extractTranslatableStrings(fixture, config);
    const out = JSON.parse(
      applyTranslatedStrings(
        fixture,
        paths,
        strings.map((s) => `[de]${s}`),
      ),
    );
    expect(out.content[0].props.text).toBe('[de]About us');
    expect(out.content[2].props.items[0].description).toBe('[de]Very fast');
    expect(out.content[2].props.items[0].href).toBe('/a');
    expect(out.content[3].props.src).toBe('/pic.png');
  });

  it('leaves the original in place for a null or missing translation', () => {
    // A backend deserializing into a nullable list can hand back a literal
    // `null` element, and a short array yields `undefined`. Neither may
    // overwrite real copy.
    const { paths } = extractTranslatableStrings(fixture, config);
    const original = JSON.parse(fixture);
    const out = JSON.parse(
      applyTranslatedStrings(fixture, paths, [null as unknown as string]),
    );
    expect(out.content[0].props.text).toBe(original.content[0].props.text);
  });

  it('survives content that is not valid JSON, on both halves', () => {
    // The two are documented as exact inverses, so `apply` must not crash on
    // input that `extract` handled by returning nothing.
    expect(extractTranslatableStrings('not json', config).strings).toEqual([]);
    expect(applyTranslatedStrings('not json', [], [])).toBe('not json');
  });

  it('leaves machine-readable text fields out of the translation set', () => {
    // These are all `text`/`textarea` — indistinguishable from copy by field
    // type. A translator handed a srcset returns something reflowed, and the
    // browser then requests a URL that does not exist.
    const technical = JSON.stringify({
      content: [
        {
          type: 'Image',
          props: {
            id: 'i1',
            src: '/a.png',
            alt: 'Real copy',
            srcset: '/a-800.png 800w, /a-1600.png 1600w',
            sizes: '(max-width: 600px) 100vw, 50vw',
          },
        },
        { type: 'Html', props: { id: 'x1', html: '<b>markup</b>', height: '400px' } },
      ],
      root: { props: { title: 'P', width: 'contained' } },
    });

    const { strings } = extractTranslatableStrings(technical, config);
    expect(strings).toContain('Real copy');
    expect(strings).not.toContain('/a-800.png 800w, /a-1600.png 1600w');
    expect(strings).not.toContain('(max-width: 600px) 100vw, 50vw');
    expect(strings).not.toContain('<b>markup</b>');
    expect(strings).not.toContain('400px');
  });
});

describe('blocks nested in a slot', () => {
  // The case upstream has no equivalent for: it kept nested blocks in `zones`,
  // whereas Columns now holds them in a slot inside an array item. A walker
  // that only understands `array` fields would find the Columns block, see a
  // slot it has no rule for, and silently skip everything an author put in it.
  const nested = JSON.stringify({
    content: [
      {
        type: 'Columns',
        props: {
          id: 'c1',
          gap: 'md',
          columns: [
            {
              width: 1,
              content: [
                { type: 'Heading', props: { id: 'nh', text: 'Nested title', level: 'h2' } },
              ],
            },
            { width: 1, content: [] },
          ],
        },
      },
    ],
    root: { props: { title: 'P', width: 'contained' } },
  });

  it('reaches copy inside a column', () => {
    expect(extractTranslatableStrings(nested, config).strings).toContain('Nested title');
  });

  it('writes a translation back into the column it came from', () => {
    const { strings, paths } = extractTranslatableStrings(nested, config);
    const out = JSON.parse(
      applyTranslatedStrings(
        nested,
        paths,
        strings.map((s) => `[de]${s}`),
      ),
    );
    expect(out.content[0].props.columns[0].content[0].props.text).toBe('[de]Nested title');
  });
});

describe('pre-slots documents', () => {
  it('still reaches blocks parked in a zones map', () => {
    const zoned = JSON.stringify({
      content: [{ type: 'Columns', props: { id: 'c1', gap: 'md', columns: [] } }],
      zones: {
        'c1:col-0': [{ type: 'Heading', props: { id: 'zh', text: 'Zoned', level: 'h2' } }],
      },
      root: { props: { title: 'P', width: 'contained' } },
    });
    expect(extractTranslatableStrings(zoned, config).strings).toContain('Zoned');
  });
});
