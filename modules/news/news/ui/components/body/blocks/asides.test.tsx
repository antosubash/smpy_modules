import { describe, expect, it } from 'vitest';
import { CalloutBlock, DefinitionsBlock, KeyPointsBlock, SourcesBlock } from './asides';
import { renderBlock } from './renderBlock';

describe('KeyPoints', () => {
  it('renders nothing at all when it has no points', () => {
    // An empty summary box is worse than none: it is a bordered hole at the top
    // of the article, and a writer who added the block and moved on gets one.
    expect(renderBlock(KeyPointsBlock)).toBe('');
    expect(renderBlock(KeyPointsBlock, { items: '  \n  ' })).toBe('');
  });

  it('lists each point and keeps the heading', () => {
    const markup = renderBlock(KeyPointsBlock, {
      items: 'All four plots are live\nTwo months ahead of schedule',
    });
    expect(markup).toContain('What you need to know');
    expect(markup).toContain('<li>All four plots are live</li>');
    expect(markup).toContain('<li>Two months ahead of schedule</li>');
  });

  it('drops the heading when it is cleared, rather than showing an empty label', () => {
    const markup = renderBlock(KeyPointsBlock, { title: '', items: 'One point' });
    expect(markup).toContain('One point');
    expect(markup).not.toContain('uppercase');
  });
});

describe('Callout', () => {
  it('renders nothing without text', () => {
    expect(renderBlock(CalloutBlock)).toBe('');
    expect(renderBlock(CalloutBlock, { text: '   ' })).toBe('');
  });

  it('names the kind when no label is given', () => {
    expect(
      renderBlock(CalloutBlock, { tone: 'correction', text: 'An earlier version…' }),
    ).toContain('Correction');
    expect(renderBlock(CalloutBlock, { tone: 'note', text: 'x' })).toContain('Note');
  });

  it('prefers the writer’s own label', () => {
    const markup = renderBlock(CalloutBlock, {
      tone: 'important',
      title: 'Editor’s note',
      text: 'x',
    });
    expect(markup).toContain('Editor’s note');
    expect(markup).not.toContain('Important');
  });

  it('carries a different colour per kind, as whole class names', () => {
    // Whole names because Tailwind reads this package as source text: a class
    // assembled at runtime is one it never emits, and the callout would render
    // with no colour at all on a fresh build.
    expect(renderBlock(CalloutBlock, { tone: 'note', text: 'x' })).toContain('border-sky-300');
    expect(renderBlock(CalloutBlock, { tone: 'important', text: 'x' })).toContain(
      'border-amber-300',
    );
    expect(renderBlock(CalloutBlock, { tone: 'correction', text: 'x' })).toContain(
      'border-rose-300',
    );
  });

  it('falls back to the note styling for a tone it does not know', () => {
    // A document hand-edited, or written against a later version of this block,
    // still has to render as something.
    expect(renderBlock(CalloutBlock, { tone: 'urgent', text: 'x' })).toContain('border-sky-300');
  });

  it('keeps a writer’s line breaks', () => {
    expect(renderBlock(CalloutBlock, { text: 'one\ntwo' })).toContain('whitespace-pre-line');
  });
});

describe('Definitions', () => {
  it('renders nothing when empty', () => {
    expect(renderBlock(DefinitionsBlock)).toBe('');
  });

  it('pairs each term with its meaning as a description list', () => {
    const markup = renderBlock(DefinitionsBlock, {
      items: 'Canopy cover | The share of ground shaded from above.',
    });
    expect(markup).toContain('<dl');
    expect(markup).toContain('Canopy cover');
    expect(markup).toContain('The share of ground shaded from above.');
  });

  it('keeps a meaning containing a pipe intact', () => {
    expect(renderBlock(DefinitionsBlock, { items: 'Term | a | b' })).toContain('a | b');
  });
});

describe('Sources', () => {
  it('renders nothing when empty', () => {
    expect(renderBlock(SourcesBlock)).toBe('');
  });

  it('links a source that has a URL, and opens it away from the article', () => {
    const markup = renderBlock(SourcesBlock, {
      items: 'Sensor rollout report | https://example.org/report',
    });
    expect(markup).toContain('href="https://example.org/report"');
    expect(markup).toContain('rel="noopener noreferrer nofollow"');
    expect(markup).toContain('Sensor rollout report');
  });

  it('still renders a source with nowhere to point', () => {
    // An interview or a book is a source; requiring a URL would push it into a
    // paragraph where it stops being attribution.
    const markup = renderBlock(SourcesBlock, { items: 'Interview, March 2024' });
    expect(markup).toContain('Interview, March 2024');
    expect(markup).not.toContain('<a ');
  });

  it('shows the URL itself when no label was written', () => {
    const markup = renderBlock(SourcesBlock, { items: ' | https://example.org/a' });
    expect(markup).toContain('>https://example.org/a</a>');
  });
});
