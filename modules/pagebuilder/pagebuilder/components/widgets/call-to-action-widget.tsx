/** CallToActionWidget: field definitions and config assembly.
 *  Types, helpers and render live in call-to-action-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import { createImageField, mediaLibraryAdapter } from '../../fields';

import { type CallToActionWidgetProps, CallToActionWidgetRender } from './call-to-action-render';

export type * from './call-to-action-render';

export const CallToActionWidget: ComponentConfig<CallToActionWidgetProps> = {
  label: 'Call to action',
  fields: {
    surface: {
      type: 'select',
      label: 'Surface',
      options: [
        { label: 'Default (accent)', value: 'default' },
        { label: 'Lime band', value: 'lime' },
        { label: 'Soft band (links)', value: 'soft' },
        { label: 'Related links band', value: 'related' },
      ],
    },
    surfaceColor: {
      type: 'text',
      label: 'Surface color (CSS, white text — optional)',
    },
    eyebrow: { type: 'text', label: 'Eyebrow' },
    align: {
      type: 'select',
      label: 'Alignment',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Center', value: 'center' },
      ],
    },
    heading: { type: 'text', label: 'Heading' },
    subheading: { type: 'textarea', label: 'Subheading' },
    primaryLabel: { type: 'text', label: 'Primary label' },
    primaryHref: { type: 'text', label: 'Primary link' },
    secondaryLabel: { type: 'text', label: 'Secondary label' },
    secondaryHref: { type: 'text', label: 'Secondary link' },
    links: {
      type: 'array',
      label: 'Links (soft band)',
      arrayFields: {
        label: { type: 'text', label: 'Label' },
        href: { type: 'text', label: 'URL' },
      },
      defaultItemProps: { label: 'Link', href: '#' },
      min: 1,
      max: 6,
    },
    images: {
      type: 'array',
      label: 'Images (lime band)',
      arrayFields: {
        src: createImageField(mediaLibraryAdapter, 'Image'),
        alt: { type: 'text', label: 'Alt text' },
        caption: { type: 'text', label: 'Caption' },
      },
      defaultItemProps: { src: '', alt: '', caption: '' },
      min: 1,
      max: 8,
    },
  },
  defaultProps: {
    surface: 'default',
    surfaceColor: '',
    align: 'left',
    eyebrow: '',
    heading: 'Start contributing today.',
    subheading: 'Add a place, a photo, or a story — every contribution counts.',
    primaryLabel: 'Get started',
    primaryHref: '#',
    secondaryLabel: 'Learn more',
    secondaryHref: '#',
    links: [],
    images: [],
  },
  render: (props) => <CallToActionWidgetRender {...props} />,
};
