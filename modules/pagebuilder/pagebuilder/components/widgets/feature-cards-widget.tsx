/** FeatureCardsWidget: field definitions and config assembly.
 *  Types, helpers and render live in feature-cards-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
import { type FeatureCardsWidgetProps, FeatureCardsWidgetRender } from './feature-cards-render';

export type * from './feature-cards-render';

export const FeatureCardsWidget: ComponentConfig<FeatureCardsWidgetProps> = {
  label: keys.pagebuilder.blocks.feature_cards.label,
  fields: {
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.eyebrow },
    title: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.title },
    subtitle: { type: 'textarea', label: keys.pagebuilder.blocks.feature_cards.subtitle },
    linkLabel: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.link_label },
    linkHref: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.link_href },
    cardLinkLabel: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.card_link_label },
    surface: {
      type: 'select',
      label: keys.pagebuilder.blocks.feature_cards.surface,
      options: [
        { label: keys.pagebuilder.blocks.feature_cards.surface_default, value: 'default' },
        { label: keys.pagebuilder.blocks.feature_cards.surface_muted, value: 'muted' },
      ],
    },
    cardSurface: {
      type: 'select',
      label: keys.pagebuilder.blocks.feature_cards.card_surface,
      options: [
        { label: keys.pagebuilder.blocks.feature_cards.card_surface_default, value: 'default' },
        { label: keys.pagebuilder.blocks.feature_cards.card_surface_muted, value: 'muted' },
      ],
    },
    columns: {
      type: 'select',
      label: keys.pagebuilder.blocks.feature_cards.columns,
      options: [
        { label: keys.pagebuilder.blocks.feature_cards.columns_2, value: '2' },
        { label: keys.pagebuilder.blocks.feature_cards.columns_3, value: '3' },
        { label: keys.pagebuilder.blocks.feature_cards.columns_4, value: '4' },
      ],
    },
    items: {
      type: 'array',
      label: keys.pagebuilder.blocks.feature_cards.items,
      arrayFields: {
        title: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.items_title },
        // The whole card is a link, so markdown links in this copy render
        // as their label text only — say so where the editor can see it.
        description: {
          type: 'textarea',
          label: keys.pagebuilder.blocks.feature_cards.items_description,
        },
        icon: {
          type: 'select',
          label: keys.pagebuilder.blocks.feature_cards.items_icon,
          options: [
            { label: keys.pagebuilder.blocks.feature_cards.items_icon_blank, value: '' },
            { label: keys.pagebuilder.blocks.feature_cards.items_icon_chart, value: 'chart' },
            { label: keys.pagebuilder.blocks.feature_cards.items_icon_search, value: 'search' },
            {
              label: keys.pagebuilder.blocks.feature_cards.items_icon_thermometer,
              value: 'thermometer',
            },
            { label: keys.pagebuilder.blocks.feature_cards.items_icon_tree, value: 'tree' },
            { label: keys.pagebuilder.blocks.feature_cards.items_icon_paw, value: 'paw' },
            { label: keys.pagebuilder.blocks.feature_cards.items_icon_waves, value: 'waves' },
          ],
        },
        iconBg: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.items_icon_bg },
        iconUrl: createImageField(
          mediaLibraryAdapter,
          keys.pagebuilder.blocks.feature_cards.items_icon_url,
        ),
        iconAlt: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.items_icon_alt },
        href: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.items_href },
        tag: { type: 'text', label: keys.pagebuilder.blocks.feature_cards.items_tag },
        cardBg: {
          type: 'text',
          label: keys.pagebuilder.blocks.feature_cards.items_card_bg,
        },
      },
      defaultItemProps: {
        title: 'Card title',
        description: 'Short description.',
        icon: '',
        iconBg: '',
        iconUrl: '',
        iconAlt: '',
        href: '#',
        tag: '',
        cardBg: '',
      },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    eyebrow: '',
    title: 'Featured topics',
    subtitle: '',
    linkLabel: '',
    linkHref: '',
    cardLinkLabel: 'Learn more',
    surface: 'default',
    cardSurface: 'default',
    columns: '3',
    items: [
      {
        title: 'First topic',
        description: 'Short description of the topic.',
        icon: '',
        iconBg: '',
        iconUrl: '',
        href: '#',
      },
      {
        title: 'Second topic',
        description: 'Short description of the topic.',
        icon: '',
        iconBg: '',
        iconUrl: '',
        href: '#',
      },
      {
        title: 'Third topic',
        description: 'Short description of the topic.',
        icon: '',
        iconBg: '',
        iconUrl: '',
        href: '#',
      },
    ],
  },
  render: (props) => <FeatureCardsWidgetRender {...props} />,
};
