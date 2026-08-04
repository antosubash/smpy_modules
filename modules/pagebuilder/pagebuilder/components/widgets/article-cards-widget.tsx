/** ArticleCards widget: field definitions and config assembly.
 *  Types and the grid itself live in article-cards-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import { createImageField, mediaLibraryAdapter } from '../../fields';
import { ArticleCardsGrid, type ArticleCardsWidgetProps } from './article-cards-render';

export type { ArticleCardItem, ArticleCardsWidgetProps } from './article-cards-render';
export { ArticleCardsGrid } from './article-cards-render';

export const ArticleCardsWidget: ComponentConfig<ArticleCardsWidgetProps> = {
  label: 'Article cards (image-top, with category & date)',
  fields: {
    title: { type: 'text', label: 'Title' },
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
      label: 'Articles',
      arrayFields: {
        imageUrl: createImageField(mediaLibraryAdapter, 'Image'),
        imageAlt: { type: 'text', label: 'Image alt text' },
        eyebrow: { type: 'text', label: 'Category tag' },
        date: { type: 'text', label: 'Date' },
        title: { type: 'text', label: 'Title' },
        // The whole card is a link, so markdown links in this copy render
        // as their label text only — say so where the editor can see it.
        body: { type: 'textarea', label: 'Body (links not supported here)' },
        href: { type: 'text', label: 'Link' },
      },
      defaultItemProps: {
        imageUrl: '',
        imageAlt: '',
        eyebrow: 'Category tag',
        date: 'MMM DD, YYYY',
        title: 'Article title goes here and may be on two lines',
        body: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit.',
        href: '#',
      },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    title: 'Latest news, updates & events',
    viewAllLabel: 'View all',
    viewAllHref: '#',
    columns: '4',
    items: [
      {
        imageUrl: '',
        imageAlt: '',
        eyebrow: 'Category tag',
        date: 'MMM DD, YYYY',
        title: 'Article title goes here and may be on two lines',
        body: 'Lorem ipsum dolor sit amet, consectetur adipiscing elit.',
        href: '#',
      },
    ],
  },
  render: ArticleCardsGrid,
};
