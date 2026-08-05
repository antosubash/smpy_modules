import type { ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ImageBlock } from './Image';

// Puck passes its own `id`/`puck` props alongside the authored ones; the block
// reads none of them, so these tests supply the authored props alone.
const Image = ImageBlock.render as unknown as (props: Record<string, unknown>) => ReactElement;

const BASE = {
  ...ImageBlock.defaultProps,
  src: '/media/pagebuilder/atlas-map.jpg',
  alt: 'The Global Canopy Atlas interactive map',
};

function html(props: Record<string, unknown> = {}): string {
  return renderToStaticMarkup(<Image {...BASE} {...props} />);
}

describe('ImageBlock caption', () => {
  it('offers a Caption field in the inspector', () => {
    expect(ImageBlock.fields?.caption).toEqual({ type: 'text', label: 'Caption' });
  });

  it('defaults to no caption', () => {
    expect(ImageBlock.defaultProps?.caption).toBe('');
  });

  it('renders the caption in a figcaption inside a figure', () => {
    const markup = html({ caption: 'Image caption goes here, if CMS field is populated' });
    expect(markup).toContain('<figure');
    expect(markup).toContain('<figcaption');
    expect(markup).toContain('Image caption goes here, if CMS field is populated');
  });

  it('takes the caption’s colour and metrics from the design pack', () => {
    // A tenant restyles captions by overriding tokens, not by patching this
    // block — same contract the widget set gives the rest of the page.
    const markup = html({ caption: 'A caption' });
    expect(markup).toContain('--pb-caption-color');
    expect(markup).toContain('--pb-body-color');
    expect(markup).toContain('--pb-caption-size');
  });

  it('keeps alt and caption separate', () => {
    // alt is the accessible description, caption is visible prose; the two are
    // rarely the same sentence, so neither may stand in for the other.
    const markup = html({ alt: 'A map of the world', caption: 'Figure 1' });
    expect(markup).toContain('alt="A map of the world"');
    expect(markup).toContain('>Figure 1</figcaption>');
  });

  it('escapes caption text rather than emitting it as markup', () => {
    expect(html({ caption: '<b>bold</b>' })).not.toContain('<b>bold</b>');
  });

  it('emits a bare <img> when no caption is set', () => {
    // Existing pages carry no caption prop at all and must render exactly as
    // they did before the field existed.
    const markup = html();
    expect(markup).not.toContain('figure');
    expect(markup.startsWith('<img')).toBe(true);
    expect(markup).toContain('class="my-3"');
  });

  it('treats an empty caption as no caption', () => {
    expect(html({ caption: '' })).toBe(html());
  });

  it('leaves the empty-src placeholder alone', () => {
    const markup = html({ src: '', caption: 'A caption' });
    expect(markup).toContain('No image selected');
    expect(markup).not.toContain('figcaption');
  });

  it('still hides a decorative image from screen readers', () => {
    const markup = html({ altKind: 'decorative', caption: 'A caption' });
    expect(markup).toContain('alt=""');
    expect(markup).toContain('aria-hidden="true"');
    expect(markup).toContain('<figcaption');
  });
});
