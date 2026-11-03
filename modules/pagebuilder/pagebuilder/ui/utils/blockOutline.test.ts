import type { Data } from '@puckeditor/core';
import { describe, expect, it } from 'vitest';

import {
  blockLabels,
  humanizeBlockType,
  moveBlock,
  outlineOf,
  summarizeProps,
} from './blockOutline';

function page(content: unknown[]): Data {
  return { content, root: { props: { title: 'Page' } } } as unknown as Data;
}

describe('humanizeBlockType', () => {
  it('splits the palette key into words', () => {
    expect(humanizeBlockType('CallToAction')).toBe('Call to action');
    expect(humanizeBlockType('AppStoreBadges')).toBe('App store badges');
    expect(humanizeBlockType('Heading')).toBe('Heading');
  });

  it('leaves a type it cannot split alone rather than blanking it', () => {
    expect(humanizeBlockType('')).toBe('');
    expect(humanizeBlockType('x')).toBe('X');
  });
});

describe('summarizeProps', () => {
  it('prefers a naming prop over a longer one', () => {
    // The whole point: an Image's `src` is longer than its `alt`, and a URL is
    // a worse answer to "which block is this" than even a short description.
    const summary = summarizeProps({
      id: 'i1',
      src: 'https://cdn.example.org/very/long/path/to/an/image-2048x1536.png',
      alt: 'Canopy',
    });
    expect(summary).toBe('Canopy');
  });

  it('falls back to the longest string when nothing is named', () => {
    expect(summarizeProps({ id: 'x', size: 'lg', quote: 'The trees are fine' })).toBe(
      'The trees are fine',
    );
  });

  it('never returns the block id', () => {
    expect(summarizeProps({ id: 'some-long-uuid-like-value' })).toBe('');
  });

  it('collapses whitespace and clamps long text', () => {
    const long = `${'a'.repeat(80)}`;
    expect(summarizeProps({ text: `  two   words  ` })).toBe('two words');
    expect(summarizeProps({ text: long })).toHaveLength(60);
    expect(summarizeProps({ text: long }).endsWith('…')).toBe(true);
  });
});

describe('blockLabels', () => {
  it('reads the palette label off each component', () => {
    expect(blockLabels({ Hero: { label: 'Hero' }, Faq: { label: 'FAQ' } })).toEqual({
      Hero: 'Hero',
      Faq: 'FAQ',
    });
  });

  it('skips components with no usable label rather than inventing one', () => {
    // Left out, not blanked: `outlineOf` falls back to humanizing the type,
    // and an empty string here would win over that and label nothing.
    expect(blockLabels({ A: {}, B: { label: '' }, C: { label: 7 }, D: null })).toEqual({});
  });
});

describe('outlineOf', () => {
  it('prefers the palette label over the humanized type', () => {
    const entries = outlineOf(page([{ type: 'Faq', props: { id: 'a' } }]), { Faq: 'FAQ' });
    expect(entries[0].label).toBe('FAQ');
  });

  it('humanizes the type when a block carries no label', () => {
    const entries = outlineOf(page([{ type: 'CustomThing', props: { id: 'a' } }]), {});
    expect(entries[0].label).toBe('Custom thing');
  });

  it('names each block and keeps document order', () => {
    const entries = outlineOf(
      page([
        { type: 'Hero', props: { id: 'a', title: 'Welcome' } },
        { type: 'CallToAction', props: { id: 'b', label: 'Sign up' } },
      ]),
    );
    expect(entries.map((e) => [e.id, e.label, e.summary])).toEqual([
      ['a', 'Hero', 'Welcome'],
      ['b', 'Call to action', 'Sign up'],
    ]);
  });

  it('survives data with no content at all', () => {
    expect(outlineOf(null)).toEqual([]);
    expect(outlineOf({} as Data)).toEqual([]);
  });

  it('falls back to a positional id so the list can still be keyed', () => {
    expect(outlineOf(page([{ type: 'Divider' }]))[0].id).toBe('block-0');
  });
});

describe('moveBlock', () => {
  const data = page([
    { type: 'Heading', props: { id: 'a' } },
    { type: 'Text', props: { id: 'b' } },
    { type: 'Image', props: { id: 'c' } },
  ]);
  const ids = (d: Data) =>
    (d as unknown as { content: { props: { id: string } }[] }).content.map((c) => c.props.id);

  it('steps a block down and up', () => {
    expect(ids(moveBlock(data, 0, 1))).toEqual(['b', 'a', 'c']);
    expect(ids(moveBlock(data, 2, -1))).toEqual(['a', 'c', 'b']);
  });

  it('returns the input unchanged at either end', () => {
    // Identity, not equality: the ends' buttons are disabled, so a no-op move
    // must not look like an edit to autosave.
    expect(moveBlock(data, 0, -1)).toBe(data);
    expect(moveBlock(data, 2, 1)).toBe(data);
    expect(moveBlock(data, 9, 1)).toBe(data);
  });

  it('does not mutate the data it was given', () => {
    moveBlock(data, 0, 1);
    expect(ids(data)).toEqual(['a', 'b', 'c']);
  });

  it('keeps the root untouched', () => {
    const moved = moveBlock(data, 0, 1) as unknown as { root: { props: { title: string } } };
    expect(moved.root.props.title).toBe('Page');
  });
});
