/** ArticleCards widget: field definitions and config assembly.
 *  Types and the grid itself live in article-cards-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
import { ArticleCardsGrid, type ArticleCardsWidgetProps } from './article-cards-render';

export type { ArticleCardItem, ArticleCardsWidgetProps } from './article-cards-render';
export { ArticleCardsGrid } from './article-cards-render';

export const ArticleCardsWidget: ComponentConfig<ArticleCardsWidgetProps> = {
  label: keys.pagebuilder.blocks.article_cards.label,
  fields: {
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    viewAllLabel: { type: 'text', label: keys.pagebuilder.blocks.article_cards.view_all_label },
    viewAllHref: { type: 'text', label: keys.pagebuilder.blocks.article_cards.view_all_href },
    columns: {
      type: 'select',
      label: keys.pagebuilder.blocks.article_cards.columns,
      options: [
        { label: keys.pagebuilder.blocks.article_cards.columns_2, value: '2' },
        { label: keys.pagebuilder.blocks.article_cards.columns_3, value: '3' },
        { label: keys.pagebuilder.blocks.article_cards.columns_4, value: '4' },
      ],
    },
    items: {
      type: 'array',
      label: keys.pagebuilder.blocks.article_cards.items,
      arrayFields: {
        imageUrl: createImageField(
          mediaLibraryAdapter,
          keys.pagebuilder.blocks.article_cards.items_image_url,
        ),
        imageAlt: { type: 'text', label: keys.pagebuilder.blocks.article_cards.items_image_alt },
        eyebrow: { type: 'text', label: keys.pagebuilder.blocks.article_cards.items_eyebrow },
        date: { type: 'text', label: keys.pagebuilder.blocks.article_cards.items_date },
        title: { type: 'text', label: keys.pagebuilder.blocks.article_cards.items_title },
        // The whole card is a link, so markdown links in this copy render
        // as their label text only — say so where the editor can see it.
        body: { type: 'textarea', label: keys.pagebuilder.blocks.article_cards.items_body },
        href: { type: 'text', label: keys.pagebuilder.blocks.article_cards.items_href },
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
