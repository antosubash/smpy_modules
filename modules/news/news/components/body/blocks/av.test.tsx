import { describe, expect, it } from 'vitest';

import { AudioBlock, VideoBlock } from './av';
import { ComparisonBlock } from './media';
import { renderBlock } from './renderBlock';

describe('Video file', () => {
  it('renders nothing without a URL', () => {
    expect(renderBlock(VideoBlock)).toBe('');
  });

  it('gives the reader controls and does not download until they ask', () => {
    // An article can carry several of these; `preload="auto"` would bill a
    // reader who only scrolled past.
    const markup = renderBlock(VideoBlock, { url: 'https://x/a.mp4' });
    expect(markup).toContain('<video');
    expect(markup).toContain('controls');
    expect(markup).toContain('preload="metadata"');
  });

  it('uses a poster when there is one, and omits the attribute when not', () => {
    expect(
      renderBlock(VideoBlock, { url: 'https://x/a.mp4', poster: 'https://x/p.png' }),
    ).toContain('poster="https://x/p.png"');
    expect(renderBlock(VideoBlock, { url: 'https://x/a.mp4' })).not.toContain('poster=');
  });
});

describe('Audio clip', () => {
  it('renders nothing without a URL', () => {
    expect(renderBlock(AudioBlock)).toBe('');
  });

  it('labels the player, because three bare ones tell a listener nothing', () => {
    expect(renderBlock(AudioBlock, { url: 'https://x/a.mp3', title: 'The call' })).toContain(
      'aria-label="The call"',
    );
  });

  it('still carries a label when the clip was not named', () => {
    expect(renderBlock(AudioBlock, { url: 'https://x/a.mp3' })).toContain(
      'aria-label="Audio clip"',
    );
  });
});

describe('Before / after', () => {
  it('renders nothing until both halves are there', () => {
    // One half of a comparison is just an image, and the reader would be told
    // it is a "before" with nothing to compare it against.
    expect(renderBlock(ComparisonBlock)).toBe('');
    expect(renderBlock(ComparisonBlock, { beforeUrl: 'https://x/a.png' })).toBe('');
    expect(renderBlock(ComparisonBlock, { afterUrl: 'https://x/b.png' })).toBe('');
  });

  it('shows both frames with their labels', () => {
    const markup = renderBlock(ComparisonBlock, {
      beforeUrl: 'https://x/a.png',
      afterUrl: 'https://x/b.png',
    });
    expect(markup.match(/<img/g)).toHaveLength(2);
    expect(markup).toContain('Before');
    expect(markup).toContain('After');
  });

  it('describes each frame by its label rather than leaving alt empty', () => {
    const markup = renderBlock(ComparisonBlock, {
      beforeUrl: 'https://x/a.png',
      afterUrl: 'https://x/b.png',
      beforeLabel: 'March 2019',
      afterLabel: 'March 2026',
    });
    expect(markup).toContain('alt="March 2019"');
    expect(markup).toContain('alt="March 2026"');
  });

  it('keeps the two side by side rather than stacking them', () => {
    // A comparison a reader has to scroll between is one they have to hold in
    // their head instead of seeing.
    const markup = renderBlock(ComparisonBlock, {
      beforeUrl: 'https://x/a.png',
      afterUrl: 'https://x/b.png',
    });
    expect(markup).toContain('grid-cols-2');
    expect(markup).not.toContain('sm:grid-cols-2');
  });
});
