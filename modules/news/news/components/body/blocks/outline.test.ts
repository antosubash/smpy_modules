import { describe, expect, it } from 'vitest';

import {
  articleOutline,
  groupOutline,
  headingAnchor,
  type OutlineEntry,
  outlineFromMetadata,
} from './outline';

function heading(id: string, text: string, level: '2' | '3' = '2') {
  return { type: 'Heading', props: { id, text, level } };
}

const DOC = {
  content: [
    heading('h1', 'The survey'),
    { type: 'Paragraph', props: { id: 'p1', text: 'Words.' } },
    heading('h2', 'How it was done', '3'),
    heading('h3', 'What it found'),
  ],
};

describe('articleOutline', () => {
  it('lists the headings in the order a reader meets them', () => {
    expect(articleOutline(DOC).map((entry) => entry.text)).toEqual([
      'The survey',
      'How it was done',
      'What it found',
    ]);
  });

  it('keeps each heading at the level it was written at', () => {
    expect(articleOutline(DOC).map((entry) => entry.level)).toEqual([2, 3, 2]);
  });

  it('derives an anchor from the heading text', () => {
    expect(articleOutline(DOC)[0].anchor).toBe('the-survey');
  });

  it('carries the block id, which is how a heading finds its own entry', () => {
    expect(articleOutline(DOC).map((entry) => entry.blockId)).toEqual(['h1', 'h2', 'h3']);
  });

  it('leaves out a heading nobody has written yet', () => {
    // A dropped-but-empty Heading is a block in progress. A contents list with
    // a blank row in it reads as a broken list rather than an unfinished
    // article.
    const doc = { content: [heading('a', 'Real'), heading('b', '   ')] };
    expect(articleOutline(doc).map((entry) => entry.text)).toEqual(['Real']);
  });

  it('gives two headings with the same words two different anchors', () => {
    const doc = { content: [heading('a', 'Background'), heading('b', 'Background')] };
    expect(articleOutline(doc).map((entry) => entry.anchor)).toEqual([
      'background',
      'background-2',
    ]);
  });

  it('does not hand the disambiguated anchor to a heading that already wanted it', () => {
    // "Background", "Background" and "Background 2" all reach for
    // `background-2`; a counter would give it out twice and every link would
    // land on whichever element the browser found first.
    const doc = {
      content: [
        heading('a', 'Background'),
        heading('b', 'Background'),
        heading('c', 'Background 2'),
      ],
    };
    const anchors = articleOutline(doc).map((entry) => entry.anchor);
    expect(new Set(anchors).size).toBe(3);
    expect(anchors).toEqual(['background', 'background-2', 'background-2-2']);
  });

  it('still gives an anchor to a heading nothing survives the slug fold of', () => {
    const doc = { content: [heading('a', '???'), heading('b', '!!!')] };
    expect(articleOutline(doc).map((entry) => entry.anchor)).toEqual(['section', 'section-2']);
  });

  it('returns nothing for a document with no headings, or no content at all', () => {
    expect(articleOutline({ content: [{ type: 'Paragraph', props: { id: 'p' } }] })).toEqual([]);
    expect(articleOutline({ content: [] })).toEqual([]);
    expect(articleOutline({})).toEqual([]);
    expect(articleOutline(null)).toEqual([]);
    // A document hand-edited into a shape nobody expected must not throw on
    // the public page.
    expect(articleOutline({ content: 'nonsense' } as never)).toEqual([]);
  });
});

describe('outlineFromMetadata', () => {
  it('reads the outline the two screens pass', () => {
    const outline = articleOutline(DOC);
    expect(outlineFromMetadata({ outline })).toBe(outline);
  });

  it('is empty for a bag that carries no outline', () => {
    // A block rendered by anything that does not set metadata still has to
    // render.
    expect(outlineFromMetadata(undefined)).toEqual([]);
    expect(outlineFromMetadata({})).toEqual([]);
    expect(outlineFromMetadata({ outline: 'not an array' })).toEqual([]);
  });
});

describe('headingAnchor', () => {
  const outline = articleOutline({
    content: [heading('a', 'Background'), heading('b', 'Background')],
  });

  it('gives each heading the anchor the outline reserved for it', () => {
    expect(headingAnchor('a', 'Background', outline)).toBe('background');
    expect(headingAnchor('b', 'Background', outline)).toBe('background-2');
  });

  it('falls back to the slug when there is no outline to consult', () => {
    // What the outline would have produced for a heading whose text is unique,
    // so a document rendered without metadata still gets working anchors.
    expect(headingAnchor('a', 'The survey', [])).toBe('the-survey');
  });

  it('emits no id at all for a heading with nothing to slug', () => {
    // `undefined` drops the attribute. Two blank headings sharing an id would
    // be a duplicate in the document for no one's benefit.
    expect(headingAnchor('a', '', [])).toBeUndefined();
    expect(headingAnchor('a', '   ', [])).toBeUndefined();
    expect(headingAnchor(undefined, undefined, [])).toBeUndefined();
  });
});

describe('groupOutline', () => {
  const entries: OutlineEntry[] = articleOutline({
    content: [
      heading('a', 'One'),
      heading('b', 'One a', '3'),
      heading('c', 'One b', '3'),
      heading('d', 'Two'),
    ],
  });

  it('nests each sub-section under the section above it', () => {
    const sections = groupOutline(entries, true);
    expect(sections.map((section) => section.entry.text)).toEqual(['One', 'Two']);
    expect(sections[0].children.map((child) => child.text)).toEqual(['One a', 'One b']);
    expect(sections[1].children).toEqual([]);
  });

  it('drops the sub-sections entirely when asked for sections only', () => {
    const sections = groupOutline(entries, false);
    expect(sections.map((section) => section.entry.text)).toEqual(['One', 'Two']);
    expect(sections.every((section) => section.children.length === 0)).toBe(true);
  });

  it('promotes a sub-section that has no section above it', () => {
    // Unusual, but it is what the writer typed; silently leaving it out makes
    // the contents disagree with the article.
    const orphan = articleOutline({ content: [heading('a', 'Opening note', '3')] });
    expect(groupOutline(orphan, true).map((section) => section.entry.text)).toEqual([
      'Opening note',
    ]);
    expect(groupOutline(orphan, false)).toEqual([]);
  });

  it('has nothing to group in an article with no headings', () => {
    expect(groupOutline([], true)).toEqual([]);
  });
});
