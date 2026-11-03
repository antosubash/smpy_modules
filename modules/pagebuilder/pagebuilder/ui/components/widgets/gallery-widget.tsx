import type { ComponentConfig } from '@puckeditor/core';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys, translate } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';
import { renderRichText } from './_internal/rich-text';
import { maskStyle } from './_shared';

export type GalleryItem = {
  src: string;
  alt: string;
};

export type GalleryWidgetProps = {
  title: string;
  columns: '2' | '3' | '4' | '5';
  /**
   * Organic mask (SVG url, from the tenant's content) clipped over every item
   * image — e.g. the team "egg" grid. When set, items switch to the egg aspect
   * (309/382) and lose their square rounding. Empty = the standard square grid.
   */
  maskUrl?: string;
  /**
   * How each tile is framed. "square" is the default crop. "image" keeps the
   * source's own portrait proportions and does not crop or round it — for
   * artwork that already carries its shape (BioGarden's team portraits ship
   * pre-cut to organic blobs, each one different, so a single CSS mask can't
   * reproduce them).
   */
  itemShape?: 'square' | 'image';
  items: GalleryItem[];
};

const COLS_CLASS: Record<GalleryWidgetProps['columns'], string> = {
  '2': 'grid-cols-2',
  '3': 'grid-cols-2 sm:grid-cols-3',
  '4': 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4',
  '5': 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-5',
};

export const GalleryWidget: ComponentConfig<GalleryWidgetProps> = {
  label: keys.pagebuilder.blocks.gallery.label,
  fields: {
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    columns: {
      type: 'select',
      label: keys.pagebuilder.blocks.gallery.columns,
      options: [
        { label: keys.pagebuilder.blocks.gallery.columns_2, value: '2' },
        { label: keys.pagebuilder.blocks.gallery.columns_3, value: '3' },
        { label: keys.pagebuilder.blocks.gallery.columns_4, value: '4' },
        { label: keys.pagebuilder.blocks.gallery.columns_5, value: '5' },
      ],
    },
    itemShape: {
      type: 'select',
      label: keys.pagebuilder.blocks.gallery.item_shape,
      options: [
        { label: keys.pagebuilder.blocks.gallery.item_shape_square, value: 'square' },
        { label: keys.pagebuilder.blocks.gallery.item_shape_image, value: 'image' },
      ],
    },
    maskUrl: {
      type: 'text',
      label: keys.pagebuilder.blocks.gallery.mask_url,
    },
    items: {
      type: 'array',
      label: keys.pagebuilder.blocks.gallery.items,
      arrayFields: {
        src: createImageField(mediaLibraryAdapter, keys.pagebuilder.blocks.gallery.items_src),
        alt: { type: 'text', label: keys.pagebuilder.blocks.gallery.items_alt },
      },
      defaultItemProps: { src: '', alt: '' },
      min: 1,
      max: 24,
    },
  },
  defaultProps: {
    title: 'Gallery',
    columns: '3',
    maskUrl: '',
    itemShape: 'square',
    items: [
      { src: '', alt: '' },
      { src: '', alt: '' },
      { src: '', alt: '' },
    ],
  },
  render: ({ title, columns, maskUrl = '', itemShape = 'square', items }) => {
    const masked = Boolean(maskUrl);
    const maskCss = masked ? maskStyle(maskUrl) : undefined;
    // A mask still wins (unchanged behaviour); otherwise "image" tiles keep
    // their own proportions and are contained rather than cropped.
    const ownShape = !masked && itemShape === 'image';
    return (
      <section className="container mx-auto my-4">
        {title && (
          <h2 className="my-8 text-center text-4xl tracking-tight font-light sm:text-5xl lg:text-6xl leading-[1.1]">
            {renderRichText(title)}
          </h2>
        )}
        {items && items.length > 0 ? (
          <div className={cn('grid gap-2 sm:gap-4 py-2', COLS_CLASS[columns])}>
            {items.map((item, idx) => (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                key={idx}
                className={cn(
                  'overflow-hidden',
                  masked && 'aspect-[309/382]',
                  ownShape && 'aspect-[250/309]',
                  !masked && !ownShape && 'aspect-square rounded',
                )}
              >
                {item.src ? (
                  <img
                    src={item.src}
                    alt={item.alt || ''}
                    loading="lazy"
                    className={cn('w-full h-full', ownShape ? 'object-contain' : 'object-cover')}
                    style={maskCss}
                  />
                ) : (
                  <div
                    className="w-full h-full bg-gradient-to-br from-gray-200 to-gray-300"
                    style={maskCss}
                  />
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-gray-500 text-center py-4">
            {translate(keys.pagebuilder.blocks.gallery.empty)}
          </div>
        )}
      </section>
    );
  },
};
