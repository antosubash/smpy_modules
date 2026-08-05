import type { ComponentConfig } from '@puckeditor/core';
import type { CSSProperties } from 'react';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { cn } from '../../utils/widgetUtils';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import { TextLink } from './_shared/text-link';

// Hoisted heading style — constant tokens only. The fallback clamp reproduces
// the prior `text-2xl sm:text-3xl lg:text-4xl` steps: 24px on phones, 30px at
// the 640px breakpoint, 36px at 1024px.
const HEADING_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
  color: 'var(--pb-heading-color)',
  fontSize: 'var(--pb-heading-lg, clamp(1.5rem, 1.25rem + 1.5625vw, 2.25rem))',
};

export type StoryCardItem = {
  imageUrl: string;
  imageAlt: string;
  eyebrow: string;
  date: string;
  title: string;
  href: string;
};

export type StoryCardsWidgetProps = {
  title: string;
  subtitle: string;
  viewAllLabel: string;
  viewAllHref: string;
  columns: '2' | '3' | '4';
  items: StoryCardItem[];
};

const COLS_CLASS: Record<StoryCardsWidgetProps['columns'], string> = {
  '2': 'sm:grid-cols-2',
  '3': 'sm:grid-cols-2 lg:grid-cols-3',
  '4': 'sm:grid-cols-2 lg:grid-cols-4',
};

export const StoryCardsWidget: ComponentConfig<StoryCardsWidgetProps> = {
  label: 'Story cards (image with overlay text)',
  fields: {
    title: { type: 'text', label: 'Title' },
    subtitle: { type: 'textarea', label: 'Subtitle' },
    viewAllLabel: { type: 'text', label: 'View-all link label' },
    viewAllHref: { type: 'text', label: 'View-all link URL' },
    columns: {
      type: 'select',
      label: 'Columns (desktop)',
      options: [
        { label: '2', value: '2' },
        { label: '3', value: '3' },
        { label: '4', value: '4' },
      ],
    },
    items: {
      type: 'array',
      label: 'Stories',
      arrayFields: {
        imageUrl: createImageField(mediaLibraryAdapter, 'Image URL'),
        imageAlt: { type: 'text', label: 'Image alt text' },
        eyebrow: { type: 'text', label: 'Eyebrow / tag' },
        date: { type: 'text', label: 'Date' },
        title: { type: 'text', label: 'Title' },
        href: { type: 'text', label: 'Link' },
      },
      defaultItemProps: {
        imageUrl: '',
        imageAlt: '',
        eyebrow: 'Story',
        date: '',
        title: 'Story title',
        href: '#',
      },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    title: 'Get inspired',
    subtitle: '',
    viewAllLabel: '',
    viewAllHref: '',
    columns: '3',
    items: [
      {
        imageUrl: '',
        imageAlt: '',
        eyebrow: 'Story',
        date: '',
        title: 'Hear first-hand from a Farmer Cluster',
        href: '#',
      },
      {
        imageUrl: '',
        imageAlt: '',
        eyebrow: 'Story',
        date: '',
        title: "Inside Europe's biggest cluster network",
        href: '#',
      },
      {
        imageUrl: '',
        imageAlt: '',
        eyebrow: 'Story',
        date: '',
        title: 'From farm to landscape: a journey',
        href: '#',
      },
    ],
  },
  render: ({ title, subtitle, viewAllLabel, viewAllHref, columns, items }) => (
    <section className="container mx-auto px-4 py-12 sm:px-6 lg:px-8">
      {(title || subtitle || (viewAllLabel && viewAllHref)) && (
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            {title && (
              <h2 className="leading-[var(--pb-heading-leading,1.15)]" style={HEADING_STYLE}>
                {renderRichText(title)}
              </h2>
            )}
            {subtitle && (
              <RichTextBlock
                text={subtitle}
                className="mt-3 max-w-3xl text-lg"
                style={{ color: 'var(--pb-body-color)' }}
              />
            )}
          </div>
          {viewAllLabel && viewAllHref && <TextLink label={viewAllLabel} href={viewAllHref} />}
        </div>
      )}
      <div className={cn('grid gap-4 grid-cols-1', COLS_CLASS[columns])}>
        {items?.map((item, idx) => (
          <a
            // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
            key={idx}
            href={item.href || '#'}
            className="group relative block aspect-[4/5] overflow-hidden rounded-xl"
          >
            {item.imageUrl ? (
              <img
                src={item.imageUrl}
                alt={item.imageAlt || item.title}
                loading="lazy"
                className="absolute inset-0 size-full object-cover transition-transform duration-300 group-hover:scale-105"
              />
            ) : (
              <div className="absolute inset-0 bg-gradient-to-br from-primary-700 to-primary-900" />
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent" />
            {item.eyebrow && (
              <span
                data-pb-story-tag=""
                className="absolute left-4 top-4 inline-flex w-fit items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
                style={{
                  backgroundColor: 'var(--pb-card-tag-bg, var(--pb-accent))',
                  color: 'var(--pb-card-tag-color, var(--pb-accent-foreground))',
                }}
              >
                {renderRichText(item.eyebrow, { allowLinks: false })}
              </span>
            )}
            <div className="absolute inset-0 flex flex-col justify-end p-5 text-white">
              {item.date && (
                <span className="text-xs text-white/80">
                  {renderRichText(item.date, { allowLinks: false })}
                </span>
              )}
              <h3 className="mt-1 text-lg font-medium leading-snug">
                {renderRichText(item.title, { allowLinks: false })}
              </h3>
            </div>
          </a>
        ))}
      </div>
    </section>
  ),
};
