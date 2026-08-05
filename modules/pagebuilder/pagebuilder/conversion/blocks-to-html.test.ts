import { describe, expect, it } from 'vitest';

import { blocksToHtml } from './blocks-to-html';
import type { PuckBlock } from './types';

const b = (type: string, props: Record<string, unknown>): PuckBlock => ({
  type,
  props: { id: `${type}-1`, ...props },
});

describe('blocksToHtml', () => {
  it('converts a heading, accepting either level spelling', () => {
    expect(blocksToHtml([b('Heading', { text: 'Hi', level: 'h3' })]).html).toBe('<h3>Hi</h3>');
    // Upstream's spelling, in case a document ever arrives from there.
    expect(blocksToHtml([b('Heading', { text: 'Hi', level: '3' })]).html).toBe('<h3>Hi</h3>');
  });

  it('falls back to h2 for a level it cannot make sense of', () => {
    expect(blocksToHtml([b('Heading', { text: 'Hi', level: 'h9' })]).html).toBe('<h2>Hi</h2>');
    expect(blocksToHtml([b('Heading', { text: 'Hi', level: undefined })]).html).toBe(
      '<h2>Hi</h2>',
    );
  });

  it('escapes heading text', () => {
    expect(blocksToHtml([b('Heading', { text: 'a < b & c', level: 'h2' })]).html).toBe(
      '<h2>a &lt; b &amp; c</h2>',
    );
  });

  it('renders Text as markdown rather than passing it through', () => {
    // The block stores markdown, so `**x**` has to become an element. Passing
    // it through verbatim — which is right for upstream, where the field holds
    // HTML — would print the asterisks on the page.
    expect(blocksToHtml([b('Text', { text: 'Hello **world**' })]).html).toBe(
      '<p>Hello <strong>world</strong></p>',
    );
  });

  it('escapes markup inside Text instead of emitting it', () => {
    // The corollary of the above: because the field is markdown, anything
    // tag-shaped in it is literal content and must not become an element.
    expect(blocksToHtml([b('Text', { text: 'a<b are adjacent' })]).html).toBe(
      '<p>a&lt;b are adjacent</p>',
    );
  });

  it('converts a Markdown block', () => {
    expect(blocksToHtml([b('Markdown', { content: '# T' })]).html).toBe('<h1>T</h1>');
  });

  it('converts images, escaping the alt and carrying known dimensions', () => {
    expect(blocksToHtml([b('Image', { src: '/a.png', alt: 'an "image"' })]).html).toBe(
      '<img src="/a.png" alt="an &quot;image&quot;">',
    );
    expect(
      blocksToHtml([b('Image', { src: '/a.png', alt: '', width: 800, height: 600 })]).html,
    ).toBe('<img src="/a.png" alt="" width="800" height="600">');
  });

  it('treats Html as lossy unless raw markup is explicitly asked for', () => {
    // The Html widget renders its markup inside `<iframe sandbox>` because a
    // ContentEditor's input isn't fully trusted. This function's output has no
    // such boundary, so emitting it has to be a decision the caller makes.
    const { html, lossyTypes } = blocksToHtml([b('Html', { html: '<section>raw</section>' })]);
    expect(html).toBe('');
    expect(lossyTypes).toEqual(['Html']);
  });

  it('passes raw Html through when opted in', () => {
    expect(
      blocksToHtml([b('Html', { html: '<section>raw</section>' })], { includeRawHtml: true }).html,
    ).toBe('<section>raw</section>');
  });

  it('attributes a quote from whichever of author and source is filled in', () => {
    expect(blocksToHtml([b('Quote', { quote: 'Q', author: 'A', source: 'S' })]).html).toBe(
      '<blockquote><p>Q</p><footer>A, S</footer></blockquote>',
    );
    expect(blocksToHtml([b('Quote', { quote: 'Q', author: '', source: '' })]).html).toBe(
      '<blockquote><p>Q</p></blockquote>',
    );
  });

  it('names the types it could not convert, deduplicated and in order', () => {
    const { html, lossyTypes } = blocksToHtml([
      b('Grid', {}),
      b('Heading', { text: 'Keep', level: 'h2' }),
      b('Hero', {}),
      b('Grid', {}),
    ]);
    expect(html).toBe('<h2>Keep</h2>');
    expect(lossyTypes).toEqual(['Grid', 'Hero']);
  });

  it('reports a block with missing props as lossy rather than throwing', () => {
    expect(blocksToHtml([{ type: 'Heading', props: { id: 'x' } }]).lossyTypes).toEqual([
      'Heading',
    ]);
  });

  it('returns empty output for no blocks', () => {
    expect(blocksToHtml([])).toEqual({ html: '', lossyTypes: [] });
  });
});
