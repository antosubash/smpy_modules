import type { ComponentConfig } from '@puckeditor/core';

import {
  buildSrcset,
  DEFAULT_IMAGE_SIZES,
  lookupAsset,
  type MediaAssetRead,
} from '../../utils/api';
import { MediaPicker } from './MediaPicker';

type AltKind = 'meaningful' | 'decorative';

interface ImageProps {
  src: string;
  alt: string;
  altKind: AltKind;
  /** Visible prose under the image. Distinct from `alt`, which describes the
   *  image to a screen reader — the two are rarely the same sentence. */
  caption?: string;
  width: number | null;
  height: number | null;
  objectFit: 'cover' | 'contain' | 'fill';
  srcset: string;
  sizes: string;
}

// Captions read their look from the design pack the way the widget set does,
// so a tenant restyles them by overriding tokens instead of patching this
// block. `--pb-caption-color` falls through to the pack's body colour, which
// is what an unstyled pack (and widgets-base) already defines.
const CAPTION_CLASS =
  'mt-2 text-[length:var(--pb-caption-size,0.875rem)] leading-[var(--pb-body-leading,1.625)]';
const CAPTION_STYLE = { color: 'var(--pb-caption-color, var(--pb-body-color))' };

function resolveSizes(srcset: string, sizes: string): string | undefined {
  if (sizes) return sizes;
  // Browsers assume 100vw when sizes is omitted but srcset is present;
  // setting it explicitly silences a console warning in dev tools.
  if (srcset) return '100vw';
  return undefined;
}

export const ImageBlock: ComponentConfig<ImageProps> = {
  label: 'Image',
  fields: {
    src: {
      type: 'custom',
      render: ({ value, onChange, readOnly }) => (
        <MediaPicker
          value={(value as string) || ''}
          onChange={(v) => onChange(v as ImageProps['src'])}
          readOnly={readOnly}
        />
      ),
    },
    altKind: {
      type: 'radio',
      options: [
        { label: 'Meaningful (describe the image)', value: 'meaningful' },
        { label: 'Decorative (hidden from screen readers)', value: 'decorative' },
      ],
    },
    alt: { type: 'text' },
    caption: { type: 'text', label: 'Caption' },
    width: { type: 'number' },
    height: { type: 'number' },
    objectFit: {
      type: 'select',
      options: [
        { label: 'Cover', value: 'cover' },
        { label: 'Contain', value: 'contain' },
        { label: 'Fill', value: 'fill' },
      ],
    },
    srcset: { type: 'textarea' },
    sizes: { type: 'text' },
  },
  defaultProps: {
    src: '',
    alt: '',
    altKind: 'meaningful',
    caption: '',
    width: null,
    height: null,
    objectFit: 'cover',
    srcset: '',
    sizes: '',
  },
  resolveData: async ({ props }, { changed }) => {
    if (!changed.src || !props.src) return { props };
    let asset: MediaAssetRead | undefined;
    try {
      asset = await lookupAsset(props.src);
    } catch {
      // Network failure mid-edit shouldn't break the editor — leave the
      // src picked and let the author fill metadata manually.
      return { props };
    }
    if (!asset) return { props };
    return {
      props: {
        ...props,
        width: asset.width ?? props.width,
        height: asset.height ?? props.height,
        srcset: buildSrcset(asset),
        // Don't clobber values the author has set by hand.
        sizes: props.sizes || DEFAULT_IMAGE_SIZES,
        alt: props.alt || asset.original_filename.replace(/\.[^.]+$/, ''),
      },
    };
  },
  render: ({ src, alt, altKind, caption, width, height, objectFit, srcset, sizes }) => {
    if (!src) {
      return (
        <div className="my-3 p-6 border-2 border-dashed border-gray-300 rounded text-center text-gray-500 text-sm">
          No image selected. Use the inspector to pick one.
        </div>
      );
    }
    const decorative = altKind === 'decorative';
    const image = (
      <img
        src={src}
        srcSet={srcset || undefined}
        sizes={resolveSizes(srcset, sizes)}
        alt={decorative ? '' : (alt ?? '')}
        role={decorative ? 'presentation' : undefined}
        aria-hidden={decorative ? true : undefined}
        width={width ?? undefined}
        height={height ?? undefined}
        loading="lazy"
        decoding="async"
        style={{ objectFit, maxWidth: '100%' }}
        // Inside a <figure> the margin belongs to the figure, and `block`
        // drops the inline descender gap above the caption. Uncaptioned
        // images keep the exact markup they had before the field existed.
        className={caption ? 'block' : 'my-3'}
      />
    );
    if (!caption) return image;
    return (
      <figure className="my-3">
        {image}
        <figcaption className={CAPTION_CLASS} style={CAPTION_STYLE}>
          {caption}
        </figcaption>
      </figure>
    );
  },
};
