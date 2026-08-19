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

  it('renders the caption as light markdown, like every other copy field', () => {
    // Table, Carousel and CallToAction captions all go through renderRichText,
    // so `**bold**` cannot mean one thing in one caption and another here.
    expect(html({ caption: '**Figure 1** — the map' })).toContain('<strong');
  });

  it('escapes caption text rather than emitting it as markup', () => {
    expect(html({ caption: '<b>bold</b>' })).not.toContain('<b>bold</b>');
  });

  it('emits a bare <img> when no caption is set', () => {
    // Existing pages carry no caption prop at all — `undefined`, not `''`, is
    // what Puck hands the block for them — and must render exactly as they did
    // before the field existed.
    //
    // `max-w-full` is the class form of the `max-width: 100%` this block used
    // to write into the style attribute, so the cap is the same one it always
    // had; it just stopped outranking every stylesheet on the page.
    const markup = html({ caption: undefined });
    expect(markup).not.toContain('figure');
    expect(markup.startsWith('<img')).toBe(true);
    expect(markup).toContain('class="my-3 max-w-full"');
  });

  it('treats an empty or blank caption as no caption', () => {
    // Whitespace-only would otherwise be truthy and render an empty caption
    // box under the image.
    const bare = html({ caption: undefined });
    expect(html({ caption: '' })).toBe(bare);
    expect(html({ caption: '   ' })).toBe(bare);
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

describe('ImageBlock measure', () => {
  // A page that uses the section widgets has to set its root to `full`, because
  // those widgets bring their own container and a `contained` root crushes
  // them. Image is a primitive: it brings no container, so on such a page it
  // spanned the whole viewport and sat flush against the window edge, with the
  // caption dragged out there with it. `maxWidth` is the measure it never had.

  it('offers a Max width field on the prose scale the widgets measure in', () => {
    // Not Container's `max-w-screen-*` scale: this caps prose-adjacent content
    // inside an article, and the article measure across this module is
    // `max-w-3xl`/`4xl`, not a viewport breakpoint.
    const field = ImageBlock.fields?.maxWidth as { options?: { value: string }[] };
    expect(field?.options?.map((o) => o.value)).toEqual(['2xl', '3xl', '4xl', '5xl', 'full']);
  });

  it('defaults to full width, so existing pages do not move', () => {
    expect(ImageBlock.defaultProps?.maxWidth).toBe('full');
    expect(ImageBlock.defaultProps?.rounded).toBe('none');
  });

  it('renders an unconstrained image exactly as it did before the field existed', () => {
    // `full` has to be a true no-op: every Image block already published
    // carries no maxWidth at all and must not shift by a pixel.
    const markup = html({ caption: undefined, maxWidth: 'full' });
    expect(markup.startsWith('<img')).toBe(true);
    expect(markup).toContain('class="my-3 max-w-full"');
    expect(markup).not.toContain('mx-auto');
  });

  it('caps and centres a constrained bare image', () => {
    const markup = html({ caption: undefined, maxWidth: '4xl' });
    expect(markup).toContain('max-w-4xl');
    expect(markup).toContain('mx-auto');
    // The measure lives on a wrapper; the <img> keeps `max-w-full` so a wide
    // image cannot overflow a column narrower than the measure (a `max-w-4xl`
    // directly on the image would outrank the 100% cap).
    expect(markup).toMatch(/<div class="[^"]*max-w-4xl[^"]*"/);
    expect(markup).toMatch(/<img[^>]*class="block max-w-full"/);
  });

  it('caps the figure, not the image, so the caption tracks the image width', () => {
    // Constraining the <img> alone would leave the <figcaption> as wide as the
    // viewport — which is the bug, just moved down one element.
    const markup = html({ caption: 'A caption', maxWidth: '4xl' });
    expect(markup).toMatch(/<figure class="[^"]*max-w-4xl[^"]*mx-auto/);
    // The image gets `max-w-full` and nothing narrower: two `max-w-*` classes
    // on one element resolve by stylesheet order, not attribute order, so the
    // measure lives on exactly one of the two elements.
    expect(markup).toMatch(/<img[^>]*class="block max-w-full"/);
  });

  it('caps through a class rather than an inline max-width', () => {
    // The block used to hard-code `max-width: 100%` in the style attribute,
    // which outranks any stylesheet and made the measure unsettable from CSS.
    expect(html({ maxWidth: '4xl' })).not.toContain('max-width:100%');
  });

  it('rounds the image when asked, mirroring Container’s scale', () => {
    expect(html({ caption: undefined, rounded: 'xl' })).toContain('rounded-xl');
    expect(html({ caption: undefined, rounded: 'none' })).not.toContain('rounded-');
  });

  it('rounds the image itself, not the figure, so corners clip the picture', () => {
    const markup = html({ caption: 'A caption', rounded: 'xl' });
    expect(markup).toMatch(/<img[^>]*rounded-xl/);
    expect(markup).not.toMatch(/<figure[^>]*rounded-xl/);
  });

  it('leaves the empty-src placeholder alone', () => {
    expect(html({ src: '', maxWidth: '4xl' })).toContain('No image selected');
  });
});
