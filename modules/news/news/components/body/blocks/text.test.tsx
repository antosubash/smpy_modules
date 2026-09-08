import { describe, expect, it } from 'vitest';

import { articleOutline } from './outline';
import { renderBlock } from './renderBlock';
import { HeadingBlock, QandABlock } from './text';

describe('Heading', () => {
  const outline = articleOutline({
    content: [
      { type: 'Heading', props: { id: 'a', text: 'Background', level: '2' } },
      { type: 'Heading', props: { id: 'b', text: 'Background', level: '3' } },
    ],
  });
  const bag = { puck: { metadata: { outline } } };

  it('carries the anchor the document reserved for it', () => {
    // Not a slug of its own text: only the document knows whether this is the
    // first "Background" or the second.
    expect(renderBlock(HeadingBlock, { ...bag, id: 'a', text: 'Background' })).toContain(
      '<h2 id="background"',
    );
    expect(
      renderBlock(HeadingBlock, { ...bag, id: 'b', text: 'Background', level: '3' }),
    ).toContain('<h3 id="background-2"');
  });

  it('is still addressable when nothing passed an outline', () => {
    expect(renderBlock(HeadingBlock, { id: 'a', text: 'The survey' })).toContain(
      '<h2 id="the-survey"',
    );
  });

  it('emits no id for a heading with nothing to slug', () => {
    const markup = renderBlock(HeadingBlock, { id: 'a', text: '   ' });
    expect(markup).toContain('<h2 class=');
    expect(markup).not.toContain('id=');
  });

  it('still starts at level 2, so the article keeps one h1', () => {
    expect(renderBlock(HeadingBlock, { id: 'a', text: 'X' })).toContain('<h2');
    expect(renderBlock(HeadingBlock, { id: 'a', text: 'X', level: '3' })).toContain('<h3');
  });
});

describe('Q&A', () => {
  it('renders nothing when empty', () => {
    expect(renderBlock(QandABlock)).toBe('');
  });

  it('pairs each question with its answer as a description list', () => {
    // A `dl` is the claim: the question introduces the answer, and a screen
    // reader announcing the pairing gives a listener what the indent gives a
    // sighted reader. Alternating `<p>`s would be neither.
    const markup = renderBlock(QandABlock, {
      items: 'Why now? | The sensors were due for replacement anyway.',
    });
    expect(markup).toContain('<dl');
    expect(markup).toContain('<dt');
    expect(markup).toContain('Why now?');
    expect(markup).toContain('The sensors were due for replacement anyway.');
  });

  it('keeps an answer that runs to several paragraphs', () => {
    expect(renderBlock(QandABlock, { items: 'Q | one\ntwo' })).toContain('whitespace-pre-line');
  });

  it('keeps an answer containing a pipe intact', () => {
    // `cells(line, 2)` folds the overflow back rather than truncating, so a
    // dash-and-pipe aside in an answer survives.
    const markup = renderBlock(QandABlock, { items: 'Q? | before | after' });
    expect(markup).toContain('before | after');
  });

  it('names the person answering only when told who', () => {
    expect(renderBlock(QandABlock, { items: 'a | b', title: 'A. Subash' })).toContain('A. Subash');
    expect(renderBlock(QandABlock, { items: 'a | b' })).not.toContain('uppercase');
  });
});
