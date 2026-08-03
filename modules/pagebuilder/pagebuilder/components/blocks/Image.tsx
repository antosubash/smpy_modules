import type { ComponentConfig } from '@measured/puck';

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
  width: number | null;
  height: number | null;
  objectFit: 'cover' | 'contain' | 'fill';
  srcset: string;
  sizes: string;
}

function resolveSizes(srcset: string, sizes: string): string | undefined {
  if (sizes) return sizes;
  // Browsers assume 100vw when sizes is omitted but srcset is present;
  // setting it explicitly silences a console warning in dev tools.
  if (srcset) return '100vw';
  return undefined;
}

export const ImageBlock: ComponentConfig<ImageProps> = {
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
  render: ({ src, alt, altKind, width, height, objectFit, srcset, sizes }) => {
    if (!src) {
      return (
        <div className="my-3 p-6 border-2 border-dashed border-gray-300 rounded text-center text-gray-500 text-sm">
          No image selected. Use the inspector to pick one.
        </div>
      );
    }
    const decorative = altKind === 'decorative';
    return (
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
        className="my-3"
      />
    );
  },
};
