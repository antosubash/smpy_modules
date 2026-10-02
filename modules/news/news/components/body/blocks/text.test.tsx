import { describe, expect, it } from 'vitest';

import { renderBlock } from './renderBlock';
import { QandABlock } from './text';

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
