import { describe, expect, it } from 'vitest';

import { ContentsBlock } from './contents';
import { articleOutline } from './outline';
import { renderBlock } from './renderBlock';

function heading(id: string, text: string, level: '2' | '3' = '2') {
  return { type: 'Heading', props: { id, text, level } };
}

const OUTLINE = articleOutline({
  content: [
    heading('a', 'The survey'),
    heading('b', 'How it was done', '3'),
    heading('c', 'What it found'),
  ],
});

/** The `puck` bag as the two screens that mount the document build it. */
function puck(outline = OUTLINE, isEditing = false) {
  return { puck: { metadata: { outline }, isEditing } };
}

describe('Contents', () => {
  it('links to every section in the article', () => {
    const markup = renderBlock(ContentsBlock, puck());
    expect(markup).toContain('href="#the-survey"');
    expect(markup).toContain('href="#what-it-found"');
    expect(markup).toContain('The survey');
  });

  it('leaves sub-sections out until asked for them', () => {
    expect(renderBlock(ContentsBlock, puck())).not.toContain('href="#how-it-was-done"');
    expect(renderBlock(ContentsBlock, { ...puck(), depth: '3' })).toContain(
      'href="#how-it-was-done"',
    );
  });

  it('nests a sub-section inside the section it belongs to', () => {
    const markup = renderBlock(ContentsBlock, { ...puck(), depth: '3' });
    // The list is a map of the document, so it carries the document's shape.
    expect(markup).toMatch(/<ol[^>]*>[\s\S]*<ol[^>]*>/);
  });

  it('renders nothing for an article with no headings', () => {
    // A reader gets silence rather than an empty box: the block is in the
    // document, but there is nothing true for it to say yet.
    expect(renderBlock(ContentsBlock, puck([]))).toBe('');
  });

  it('renders nothing for an article with only one heading', () => {
    // A one-entry contents list tells a reader nothing scrolling would not,
    // and puts a box between them and the first paragraph to do it.
    const single = articleOutline({ content: [heading('a', 'Only one')] });
    expect(renderBlock(ContentsBlock, puck(single))).toBe('');
  });

  it('says so on the canvas instead of disappearing', () => {
    // On the canvas, rendering nothing is indistinguishable from a block that
    // failed to load — and a writer who has just dropped this in has, by
    // definition, not written the headings yet.
    const markup = renderBlock(ContentsBlock, puck([], true));
    expect(markup).toContain('Heading blocks');
    expect(markup).not.toContain('<nav');
  });

  it('is a navigation landmark a reader can jump to', () => {
    expect(renderBlock(ContentsBlock, puck())).toContain('<nav aria-label="In this article"');
  });

  it('names the landmark even when the writer cleared the heading', () => {
    const markup = renderBlock(ContentsBlock, { ...puck(), title: '' });
    expect(markup).toContain('aria-label="Contents"');
  });

  it('renders on a screen that passes no outline at all', () => {
    // Every block in this palette has to survive being mounted by something
    // that does not know about it.
    expect(renderBlock(ContentsBlock)).toBe('');
  });
});
