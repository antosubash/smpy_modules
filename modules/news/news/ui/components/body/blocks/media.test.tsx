import { describe, expect, it } from 'vitest';
import { DividerBlock } from './layout';
import { GalleryBlock, ImageBlock } from './media';
import { renderBlock, renderStored } from './renderBlock';

describe('Image', () => {
  it('renders nothing without a URL', () => {
    expect(renderBlock(ImageBlock)).toBe('');
  });

  it('carries a credit alongside the caption', () => {
    const markup = renderBlock(ImageBlock, {
      url: 'https://x/a.png',
      alt: 'A sensor mast',
      caption: 'The north site.',
      credit: 'IIASA',
    });
    expect(markup).toContain('The north site.');
    expect(markup).toContain('IIASA');
  });

  it('renders a credit with no caption', () => {
    // The two are different obligations, so a picture can carry either alone.
    const markup = renderBlock(ImageBlock, { url: 'https://x/a.png', credit: 'IIASA' });
    expect(markup).toContain('<figcaption');
    expect(markup).toContain('IIASA');
  });

  it('omits the figcaption entirely when there is neither', () => {
    expect(renderBlock(ImageBlock, { url: 'https://x/a.png' })).not.toContain('<figcaption');
  });

  it('still renders a document written before credits existed', () => {
    // `credit` is simply absent from every image saved before this field, so
    // this renders the stored props alone — through `renderBlock` the default
    // would supply the very prop the test says is missing.
    const markup = renderStored(ImageBlock, { url: 'https://x/a.png', alt: '', caption: 'Old' });
    expect(markup).toContain('Old');
    expect(markup).toContain('<figcaption');
  });
});

describe('Gallery', () => {
  it('renders nothing when empty', () => {
    expect(renderBlock(GalleryBlock)).toBe('');
  });

  it('drops a line with no URL rather than rendering a broken image', () => {
    const markup = renderBlock(GalleryBlock, {
      images: 'https://x/a.png | first\n | orphaned caption\nhttps://x/b.png | second',
    });
    expect(markup.match(/<img/g)).toHaveLength(2);
    expect(markup).not.toContain('orphaned caption');
  });

  it('picks a whole grid class per column count', () => {
    expect(renderBlock(GalleryBlock, { images: 'https://x/a.png', columns: '2' })).toContain(
      'sm:grid-cols-2',
    );
    expect(renderBlock(GalleryBlock, { images: 'https://x/a.png', columns: '3' })).toContain(
      'sm:grid-cols-3',
    );
  });

  it('lazily loads, since a gallery is rarely the first thing on screen', () => {
    expect(renderBlock(GalleryBlock, { images: 'https://x/a.png' })).toContain('loading="lazy"');
  });
});

describe('Divider', () => {
  it('is a plain rule by default, so existing articles do not move', () => {
    const markup = renderBlock(DividerBlock);
    expect(markup).toContain('<hr');
    expect(markup).toContain('my-6');
  });

  it('renders a document saved before the style field existed', () => {
    // Stored props only: every divider written before `style` reaches the
    // viewer without it, and must still be the rule it has always been. This is
    // the shape `walkthroughBody` seeds, so the e2e run proves it too.
    expect(renderStored(DividerBlock, { spacing: 'large' })).toContain('<hr');
  });

  it('marks a scene break without a rule when set to an asterism', () => {
    const markup = renderBlock(DividerBlock, { style: 'asterism' });
    expect(markup).not.toContain('<hr');
    expect(markup).toContain('***');
    // Three read-out asterisks are noise; the break is carried by the spacing.
    expect(markup).toContain('aria-hidden="true"');
  });

  it('honours the spacing in both styles', () => {
    expect(renderBlock(DividerBlock, { spacing: 'large' })).toContain('my-12');
    expect(renderBlock(DividerBlock, { spacing: 'large', style: 'asterism' })).toContain('my-12');
  });
});
