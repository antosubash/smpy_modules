import type { ComponentConfig } from '@puckeditor/core';
import type { CSSProperties } from 'react';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type FeatureGridItem = {
  title: string;
  description: string;
  iconUrl: string;
};

export type FeatureGridWidgetProps = {
  heading: string;
  subtext: string;
  columns: '2' | '3' | '4';
  items: FeatureGridItem[];
};

const COLS_CLASS: Record<FeatureGridWidgetProps['columns'], string> = {
  '2': 'sm:grid-cols-2',
  '3': 'sm:grid-cols-2 lg:grid-cols-3',
  '4': 'sm:grid-cols-2 lg:grid-cols-4',
};

export const FeatureGridWidget: ComponentConfig<FeatureGridWidgetProps> = {
  label: keys.pagebuilder.blocks.feature_grid.label,
  fields: {
    heading: { type: 'text', label: keys.pagebuilder.blocks.common.heading },
    subtext: { type: 'textarea', label: keys.pagebuilder.blocks.feature_grid.subtext },
    columns: {
      type: 'select',
      label: keys.pagebuilder.blocks.feature_grid.columns,
      options: [
        { label: keys.pagebuilder.blocks.feature_grid.columns_2, value: '2' },
        { label: keys.pagebuilder.blocks.feature_grid.columns_3, value: '3' },
        { label: keys.pagebuilder.blocks.feature_grid.columns_4, value: '4' },
      ],
    },
    items: {
      type: 'array',
      label: keys.pagebuilder.blocks.feature_grid.items,
      arrayFields: {
        title: { type: 'text', label: keys.pagebuilder.blocks.feature_grid.items_title },
        description: {
          type: 'textarea',
          label: keys.pagebuilder.blocks.feature_grid.items_description,
        },
        iconUrl: createImageField(
          mediaLibraryAdapter,
          keys.pagebuilder.blocks.feature_grid.items_icon_url,
        ),
      },
      defaultItemProps: {
        title: 'Feature',
        description: 'Feature description.',
        iconUrl: '',
      },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    heading: 'Powerful features',
    subtext: 'Everything you need to build amazing pages.',
    columns: '3',
    items: [
      { title: 'Fast', description: 'Loads in milliseconds.', iconUrl: '' },
      { title: 'Flexible', description: 'Compose any layout.', iconUrl: '' },
      {
        title: 'Reliable',
        description: 'Battle-tested in production.',
        iconUrl: '',
      },
    ],
  },
  render: ({ heading, subtext, columns, items }) => (
    <section className="container px-4 py-16 mx-auto sm:max-w-xl md:max-w-full lg:max-w-screen-xl md:px-24 lg:px-8 lg:py-20">
      {(heading || subtext) && (
        <div className="max-w-xl mb-10 md:mx-auto sm:text-center lg:max-w-2xl md:mb-12">
          {heading && (
            <h2
              className="max-w-lg mb-6 text-3xl leading-tight sm:text-4xl md:mx-auto"
              style={{
                fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
                letterSpacing: 'var(--pb-display-tracking)',
                fontFamily: 'var(--pb-display-font)',
                color: 'var(--pb-heading-color)',
              }}
            >
              {renderRichText(heading)}
            </h2>
          )}
          {subtext && <RichTextBlock text={subtext} className="text-base md:text-lg" />}
        </div>
      )}
      <div className={cn('grid gap-8 grid-cols-1', COLS_CLASS[columns])}>
        {items?.map((item, idx) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
          <div key={idx} className="text-center">
            {item.iconUrl ? (
              <img
                src={item.iconUrl}
                alt=""
                loading="lazy"
                className="size-12 mx-auto mb-4 object-contain"
              />
            ) : (
              <div className="size-12 rounded-full bg-primary-100 mx-auto mb-4" />
            )}
            <h3 className="mb-3 text-xl font-medium leading-snug">{renderRichText(item.title)}</h3>
            {item.description && (
              <RichTextBlock
                text={item.description}
                className="text-sm"
                style={{ color: 'var(--pb-body-color)' }}
              />
            )}
          </div>
        ))}
      </div>
    </section>
  ),
};
