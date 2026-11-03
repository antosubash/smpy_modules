import { describe, expect, it } from 'vitest';

import { keys } from '../../../utils/i18n';
import { imageUrlField, previewNote, showsPreview, statusFor } from './imageUrlField';
import { ComparisonBlock, ImageBlock } from './media';
import { renderStored } from './renderBlock';

describe('statusFor', () => {
  it('remembers what it learned about the address it is looking at', () => {
    expect(statusFor({ url: 'a.png', status: 'failed' }, 'a.png')).toBe('failed');
    expect(statusFor({ url: 'a.png', status: 'loaded' }, 'a.png')).toBe('loaded');
  });

  it('knows nothing yet about an address it has not seen', () => {
    // A writer who pastes a good URL over a typo must not keep being told
    // nothing loaded — that reads as a broken field rather than as reporting.
    expect(statusFor({ url: 'typo.png', status: 'failed' }, 'good.png')).toBe('idle');
  });
});

describe('showsPreview', () => {
  it('draws the picture while the address might still be one', () => {
    expect(showsPreview('a.png', 'idle')).toBe(true);
    expect(showsPreview('a.png', 'loaded')).toBe(true);
  });

  it('takes the picture away once the address has failed', () => {
    // Otherwise the panel shows the browser's broken-image glyph, which says
    // nothing a writer can act on.
    expect(showsPreview('a.png', 'failed')).toBe(false);
  });

  it('shows nothing at all for an empty field', () => {
    // A placeholder box where no address has been typed is furniture.
    expect(showsPreview('', 'idle')).toBe(false);
    expect(showsPreview('   ', 'idle')).toBe(false);
  });
});

describe('previewNote', () => {
  it('says so, once, when the address loads nothing', () => {
    // The key, not the sentence — the field translates it on the way out.
    expect(previewNote('a.png', 'failed')).toBe(keys.news.blocks.image_field.not_loaded);
  });

  it('stays quiet the rest of the time', () => {
    expect(previewNote('a.png', 'idle')).toBeNull();
    expect(previewNote('a.png', 'loaded')).toBeNull();
    // An empty field is not a failure to report.
    expect(previewNote('', 'failed')).toBeNull();
  });
});

describe('imageUrlField', () => {
  it('is a custom field that carries its own label', () => {
    // Puck renders a `custom` field's `render` with no label wrapper, so the
    // field has to supply one or the panel loses the name of the input.
    const field = imageUrlField(keys.news.blocks.image.url);
    expect(field.type).toBe('custom');
    expect(typeof field.render).toBe('function');
  });

  it('is what the blocks that take one picture use', () => {
    expect(ImageBlock.fields?.url).toMatchObject({ type: 'custom' });
    expect(ComparisonBlock.fields?.beforeUrl).toMatchObject({ type: 'custom' });
    expect(ComparisonBlock.fields?.afterUrl).toMatchObject({ type: 'custom' });
  });

  it('changes nothing a reader gets', () => {
    // The field is editor-side. A document saved before it existed renders
    // exactly as it did — `renderStored`, so no default can paper over it.
    const markup = renderStored(ImageBlock, { url: 'https://example.test/a.png', alt: 'A plot' });
    expect(markup).toContain('src="https://example.test/a.png"');
    expect(markup).toContain('alt="A plot"');
    expect(markup).toContain('loading="lazy"');
  });
});
