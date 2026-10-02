/** MediaObjectWidget: field definitions and config assembly.
 *  Types, helpers and render live in media-object-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
import { imageSrcsetField, resolveImageSrcset } from './_shared';
import { type MediaObjectWidgetProps, MediaObjectWidgetRender } from './media-object-render';

export type * from './media-object-render';

export const MediaObjectWidget: ComponentConfig<MediaObjectWidgetProps> = {
  label: keys.pagebuilder.blocks.media_object.label,
  fields: {
    imageUrl: createImageField(mediaLibraryAdapter, keys.pagebuilder.blocks.media_object.image_url),
    imageAlt: { type: 'text', label: keys.pagebuilder.blocks.common.image_alt },
    imageSrcset: imageSrcsetField,
    imageMaskUrl: {
      type: 'text',
      label: keys.pagebuilder.blocks.media_object.image_mask_url,
    },
    imageShape: {
      type: 'select',
      label: keys.pagebuilder.blocks.media_object.image_shape,
      options: [
        { label: keys.pagebuilder.blocks.media_object.image_shape_rounded, value: 'rounded' },
        { label: keys.pagebuilder.blocks.media_object.image_shape_native, value: 'native' },
      ],
    },
    imageTag: { type: 'text', label: keys.pagebuilder.blocks.media_object.image_tag },
    imageTagColor: { type: 'text', label: keys.pagebuilder.blocks.media_object.image_tag_color },
    imageTagMaskUrl: {
      type: 'text',
      label: keys.pagebuilder.blocks.media_object.image_tag_mask_url,
    },
    imageTagImageUrl: {
      type: 'text',
      label: keys.pagebuilder.blocks.media_object.image_tag_image_url,
    },
    imagePosition: {
      type: 'select',
      label: keys.pagebuilder.blocks.media_object.image_position,
      options: [
        { label: keys.pagebuilder.blocks.media_object.image_position_left, value: 'left' },
        { label: keys.pagebuilder.blocks.media_object.image_position_right, value: 'right' },
      ],
    },
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.media_object.eyebrow },
    datePill: { type: 'text', label: keys.pagebuilder.blocks.media_object.date_pill },
    datePillColor: { type: 'text', label: keys.pagebuilder.blocks.media_object.date_pill_color },
    heading: { type: 'text', label: keys.pagebuilder.blocks.common.heading },
    body: { type: 'textarea', label: keys.pagebuilder.blocks.common.body },
    linkLabel: { type: 'text', label: keys.pagebuilder.blocks.media_object.link_label },
    linkHref: { type: 'text', label: keys.pagebuilder.blocks.media_object.link_href },
    headingWidth: {
      type: 'select',
      label: keys.pagebuilder.blocks.media_object.heading_width,
      options: [
        { label: keys.pagebuilder.blocks.media_object.heading_width_auto, value: 'auto' },
        { label: keys.pagebuilder.blocks.media_object.heading_width_narrow, value: 'narrow' },
      ],
    },
    layout: {
      type: 'select',
      label: keys.pagebuilder.blocks.media_object.layout,
      options: [
        { label: keys.pagebuilder.blocks.media_object.layout_half, value: 'half' },
        { label: keys.pagebuilder.blocks.media_object.layout_grid, value: 'grid' },
        { label: keys.pagebuilder.blocks.media_object.layout_banner, value: 'banner' },
      ],
    },
    textWidth: {
      type: 'select',
      label: keys.pagebuilder.blocks.media_object.text_width,
      options: [
        { label: keys.pagebuilder.blocks.media_object.text_width_auto, value: 'auto' },
        { label: keys.pagebuilder.blocks.media_object.text_width_xs, value: 'xs' },
        { label: keys.pagebuilder.blocks.media_object.text_width_sm, value: 'sm' },
        { label: keys.pagebuilder.blocks.media_object.text_width_md, value: 'md' },
      ],
    },
    bullets: {
      type: 'array',
      label: keys.pagebuilder.blocks.media_object.bullets,
      arrayFields: {
        title: { type: 'text', label: keys.pagebuilder.blocks.media_object.bullets_title },
        body: { type: 'textarea', label: keys.pagebuilder.blocks.media_object.bullets_body },
      },
      defaultItemProps: { title: '', body: '' },
      min: 0,
      max: 12,
    },
    bulletSize: {
      type: 'select',
      label: keys.pagebuilder.blocks.media_object.bullet_size,
      options: [
        { label: keys.pagebuilder.blocks.media_object.bullet_size_md, value: 'md' },
        { label: keys.pagebuilder.blocks.media_object.bullet_size_lg, value: 'lg' },
      ],
    },
    bodyMaxWidth: { type: 'text', label: keys.pagebuilder.blocks.media_object.body_max_width },
    footnote: { type: 'text', label: keys.pagebuilder.blocks.media_object.footnote },
    linkVariant: {
      type: 'select',
      label: keys.pagebuilder.blocks.media_object.link_variant,
      options: [
        { label: keys.pagebuilder.blocks.media_object.link_variant_link, value: 'link' },
        { label: keys.pagebuilder.blocks.media_object.link_variant_button, value: 'button' },
      ],
    },
    bulletMarker: {
      type: 'select',
      label: keys.pagebuilder.blocks.media_object.bullet_marker,
      options: [
        { label: keys.pagebuilder.blocks.media_object.bullet_marker_square, value: 'square' },
        { label: keys.pagebuilder.blocks.media_object.bullet_marker_none, value: 'none' },
      ],
    },
    logos: {
      type: 'array',
      label: keys.pagebuilder.blocks.media_object.logos,
      arrayFields: {
        src: createImageField(mediaLibraryAdapter, keys.pagebuilder.blocks.media_object.logos_src),
        alt: { type: 'text', label: keys.pagebuilder.blocks.media_object.logos_alt },
      },
      defaultItemProps: { src: '', alt: '' },
      // Explicit 0: the strip is optional (defaultProps ships []) — declared
      // so the hardening sweep still sees a bounded array field.
      min: 0,
      max: 8,
    },
    surface: {
      type: 'select',
      label: keys.pagebuilder.blocks.media_object.surface,
      options: [
        { label: keys.pagebuilder.blocks.media_object.surface_default, value: 'default' },
        { label: keys.pagebuilder.blocks.media_object.surface_dark, value: 'dark' },
        { label: keys.pagebuilder.blocks.media_object.surface_muted, value: 'muted' },
      ],
    },
    surfaceColor: {
      type: 'text',
      label: keys.pagebuilder.blocks.common.surface_color,
    },
  },
  defaultProps: {
    imageUrl: '',
    imageAlt: '',
    imageSrcset: '',
    imageMaskUrl: '',
    imageShape: 'rounded',
    imageTag: '',
    imageTagColor: '',
    imageTagMaskUrl: '',
    imageTagImageUrl: '',
    imagePosition: 'left',
    eyebrow: '',
    datePill: '',
    datePillColor: '',
    heading: 'Section heading',
    body: 'Body text describing the section.',
    linkLabel: 'Learn more',
    linkHref: '#',
    bodyMaxWidth: '',
    footnote: '',
    bullets: [],
    bulletSize: 'md',
    bulletMarker: 'square',
    linkVariant: 'link',
    logos: [],
    headingWidth: 'auto',
    layout: 'half',
    textWidth: 'auto',
    surface: 'default',
    surfaceColor: '',
  },
  resolveData: resolveImageSrcset,
  render: (props) => <MediaObjectWidgetRender {...props} />,
};
