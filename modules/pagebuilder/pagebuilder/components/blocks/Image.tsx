import type { ComponentConfig } from '@puckeditor/core';

import {
  buildSrcset,
  DEFAULT_IMAGE_SIZES,
  lookupAsset,
  type MediaAssetRead,
} from '../../utils/api';
import { MEASURE_OPTIONS, type Measure, measureClass } from '../../utils/measure';
import { cn } from '../../utils/widgetUtils';
import { renderRichText } from '../widgets/_internal/rich-text';
import { MediaPicker } from './MediaPicker';

type AltKind = 'meaningful' | 'decorative';
type Rounding = 'none' | 'md' | 'lg' | 'xl';

interface ImageProps {
  src: string;
  alt: string;
  altKind: AltKind;
  /** Visible prose under the image, as light markdown. Distinct from `alt`,
   *  which describes the image to a screen reader — the two are rarely the
   *  same sentence. */
  caption?: string;
  /** How wide the picture is allowed to run. A page built from the section
   *  widgets has to set its root to `full` — those widgets bring their own
   *  container and a `contained` root crushes them — which leaves this block,
   *  a primitive that brings no container, spanning the whole viewport. */
  maxWidth: Measure;
  rounded: Rounding;
  width: number | null;
  height: number | null;
  objectFit: 'cover' | 'contain' | 'fill';
  srcset: string;
  sizes: string;
}

// `none` emits nothing rather than Container's `rounded-none`: every Image
// already published carries no `rounded` prop, and the default has to leave
// their markup byte-identical.
const ROUNDED_CLASS: Record<Rounding, string> = {
  none: '',
  md: 'rounded-md',
  lg: 'rounded-lg',
  xl: 'rounded-xl',
};

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
    maxWidth: { type: 'select', label: 'Max width', options: MEASURE_OPTIONS },
    rounded: {
      type: 'select',
      label: 'Rounded',
      options: [
        { label: 'None', value: 'none' },
        { label: 'Medium', value: 'md' },
        { label: 'Large', value: 'lg' },
        { label: 'Extra Large', value: 'xl' },
      ],
    },
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
    // Both default to the shape the block had before these fields existed, so
    // adding them moves no published page.
    maxWidth: 'full',
    rounded: 'none',
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
        // The asset's own alt text first: it is a description of the picture
        // written by a person, which a filename is not. The filename stays as
        // the last resort so an undescribed asset still yields something.
        alt: props.alt || asset.alt_text || asset.original_filename.replace(/\.[^.]+$/, ''),
      },
    };
  },
  render: ({
    src,
    alt,
    altKind,
    caption,
    maxWidth,
    rounded,
    width,
    height,
    objectFit,
    srcset,
    sizes,
  }) => {
    if (!src) {
      return (
        <div className="my-3 p-6 border-2 border-dashed border-gray-300 rounded text-center text-gray-500 text-sm">
          No image selected. Use the inspector to pick one.
        </div>
      );
    }
    const decorative = altKind === 'decorative';
    // Trimmed, so a caption of nothing but spaces is no caption: it would
    // otherwise render an empty <figcaption> box under the image. Same rule
    // the translation extractor applies to every other copy field.
    const hasCaption = Boolean(caption?.trim());
    const measure = measureClass(maxWidth);
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
        // The cap used to be an inline `max-width: 100%`, which outranks every
        // stylesheet and put the measure out of reach of both this field and a
        // tenant's design pack. As a class it is settable and still caps at the
        // container when `maxWidth` is `full`.
        style={{ objectFit }}
        // Inside a <figure> the margin belongs to the figure, and `block`
        // drops the inline descender gap above the caption. The measure goes on
        // whichever element is outermost — two `max-w-*` classes on one element
        // would resolve by stylesheet order, not by which one was meant.
        className={cn(
          hasCaption ? 'block max-w-full' : cn('my-3', measure),
          ROUNDED_CLASS[rounded],
        )}
      />
    );
    if (!hasCaption) return image;
    return (
      // Capping the figure rather than the image keeps the caption the same
      // width as the picture it describes.
      <figure className={cn('my-3', measure)}>
        {image}
        <figcaption className={CAPTION_CLASS} style={CAPTION_STYLE}>
          {/* Light markdown, like every other copy field in the module — the
              Table/Carousel/CallToAction captions all render this way, so
              `**Figure 1**` can't work in one caption and not another. */}
          {renderRichText(caption)}
        </figcaption>
      </figure>
    );
  },
};
