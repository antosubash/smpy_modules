/** FeatureCardsWidget: field definitions and config assembly.
 *  Types, helpers and render live in feature-cards-render.tsx. */

import type { ComponentConfig } from '@measured/puck';

import { type FeatureCardsWidgetProps, FeatureCardsWidgetRender } from './feature-cards-render';

export type * from './feature-cards-render';

export const FeatureCardsWidget: ComponentConfig<FeatureCardsWidgetProps> = {
  label: 'Feature cards (linked grid)',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow (left of title)' },
    title: { type: 'text', label: 'Section title' },
    subtitle: { type: 'textarea', label: 'Section subtitle' },
    linkLabel: { type: 'text', label: 'Header link label' },
    linkHref: { type: 'text', label: 'Header link URL' },
    cardLinkLabel: { type: 'text', label: 'Card link label' },
    surface: {
      type: 'select',
      label: 'Surface',
      options: [
        { label: 'Default', value: 'default' },
        { label: 'Soft grey panel', value: 'muted' },
      ],
    },
    cardSurface: {
      type: 'select',
      label: 'Card surface',
      options: [
        { label: 'White + border', value: 'default' },
        { label: 'Soft grey', value: 'muted' },
      ],
    },
    columns: {
      type: 'select',
      label: 'Columns',
      options: [
        { label: '2', value: '2' },
        { label: '3', value: '3' },
        { label: '4', value: '4' },
      ],
    },
    items: {
      type: 'array',
      label: 'Cards',
      arrayFields: {
        title: { type: 'text', label: 'Title' },
        // The whole card is a link, so markdown links in this copy render
        // as their label text only — say so where the editor can see it.
        description: {
          type: 'textarea',
          label: 'Description (links not supported here)',
        },
        icon: {
          type: 'select',
          label: 'Icon',
          options: [
            { label: 'None', value: '' },
            { label: 'Chart', value: 'chart' },
            { label: 'Search', value: 'search' },
            { label: 'Thermometer', value: 'thermometer' },
            { label: 'Tree', value: 'tree' },
            { label: 'Paw', value: 'paw' },
            { label: 'Waves', value: 'waves' },
          ],
        },
        iconBg: { type: 'text', label: 'Icon badge colour' },
        iconUrl: { type: 'text', label: 'Icon image URL (overrides icon)' },
        iconAlt: { type: 'text', label: 'Icon image alt text' },
        href: { type: 'text', label: 'Link URL' },
        tag: { type: 'text', label: 'Tag (top-right)' },
        cardBg: {
          type: 'text',
          label: 'Card colour (CSS, white text — optional)',
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
