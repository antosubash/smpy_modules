/** CallToActionWidget: field definitions and config assembly.
 *  Types, helpers and render live in call-to-action-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
import { type CallToActionWidgetProps, CallToActionWidgetRender } from './call-to-action-render';

export type * from './call-to-action-render';

export const CallToActionWidget: ComponentConfig<CallToActionWidgetProps> = {
  label: keys.pagebuilder.blocks.call_to_action.label,
  fields: {
    surface: {
      type: 'select',
      label: keys.pagebuilder.blocks.call_to_action.surface,
      options: [
        { label: keys.pagebuilder.blocks.call_to_action.surface_default, value: 'default' },
        { label: keys.pagebuilder.blocks.call_to_action.surface_lime, value: 'lime' },
        { label: keys.pagebuilder.blocks.call_to_action.surface_soft, value: 'soft' },
        { label: keys.pagebuilder.blocks.call_to_action.surface_related, value: 'related' },
      ],
    },
    surfaceColor: {
      type: 'text',
      label: keys.pagebuilder.blocks.common.surface_color,
    },
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.call_to_action.eyebrow },
    align: {
      type: 'select',
      label: keys.pagebuilder.blocks.common.align,
      options: [
        { label: keys.pagebuilder.blocks.common.align_left, value: 'left' },
        { label: keys.pagebuilder.blocks.common.align_center, value: 'center' },
      ],
    },
    heading: { type: 'text', label: keys.pagebuilder.blocks.common.heading },
    subheading: { type: 'textarea', label: keys.pagebuilder.blocks.common.subheading },
    primaryLabel: { type: 'text', label: keys.pagebuilder.blocks.call_to_action.primary_label },
    primaryHref: { type: 'text', label: keys.pagebuilder.blocks.call_to_action.primary_href },
    secondaryLabel: { type: 'text', label: keys.pagebuilder.blocks.call_to_action.secondary_label },
    secondaryHref: { type: 'text', label: keys.pagebuilder.blocks.call_to_action.secondary_href },
    links: {
      type: 'array',
      label: keys.pagebuilder.blocks.call_to_action.links,
      arrayFields: {
        label: { type: 'text', label: keys.pagebuilder.blocks.call_to_action.links_label },
        href: { type: 'text', label: keys.pagebuilder.blocks.call_to_action.links_href },
      },
      defaultItemProps: { label: 'Link', href: '#' },
      min: 1,
      max: 6,
    },
    images: {
      type: 'array',
      label: keys.pagebuilder.blocks.call_to_action.images,
      arrayFields: {
        src: createImageField(
          mediaLibraryAdapter,
          keys.pagebuilder.blocks.call_to_action.images_src,
        ),
        alt: { type: 'text', label: keys.pagebuilder.blocks.call_to_action.images_alt },
        caption: { type: 'text', label: keys.pagebuilder.blocks.call_to_action.images_caption },
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
