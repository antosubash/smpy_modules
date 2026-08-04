/** MediaObjectWidget: field definitions and config assembly.
 *  Types, helpers and render live in media-object-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import { createImageField, mediaLibraryAdapter } from '../../fields';

import { type MediaObjectWidgetProps, MediaObjectWidgetRender } from './media-object-render';

export type * from './media-object-render';

export const MediaObjectWidget: ComponentConfig<MediaObjectWidgetProps> = {
  label: 'Media object (image + body + link)',
  fields: {
    imageUrl: createImageField(mediaLibraryAdapter, 'Image'),
    imageAlt: { type: 'text', label: 'Image alt text' },
    imageMaskUrl: {
      type: 'text',
      label: 'Image mask URL (organic shape — optional)',
    },
    imageShape: {
      type: 'select',
      label: 'Image shape',
      options: [
        { label: 'Rounded rectangle', value: 'rounded' },
        { label: "Image's own shape (transparent artwork)", value: 'native' },
      ],
    },
    imageTag: { type: 'text', label: 'Image tag (overlay top-left)' },
    imageTagColor: { type: 'text', label: 'Image tag color (CSS)' },
    imageTagMaskUrl: {
      type: 'text',
      label: 'Image tag mask URL (organic tag shape — optional)',
    },
    imageTagImageUrl: {
      type: 'text',
      label: 'Image tag artwork (transparent PNG — replaces mask + colour)',
    },
    imagePosition: {
      type: 'select',
      label: 'Image position',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Right', value: 'right' },
      ],
    },
    eyebrow: { type: 'text', label: 'Eyebrow (grid/banner layouts)' },
    datePill: { type: 'text', label: 'Date pill (above heading)' },
    datePillColor: { type: 'text', label: 'Date pill color (CSS)' },
    heading: { type: 'text', label: 'Heading' },
    body: { type: 'textarea', label: 'Body' },
    linkLabel: { type: 'text', label: 'Link label' },
    linkHref: { type: 'text', label: 'Link URL' },
    headingWidth: {
      type: 'select',
      label: 'Heading width',
      options: [
        { label: 'Auto', value: 'auto' },
        { label: 'Narrow (wrap)', value: 'narrow' },
      ],
    },
    layout: {
      type: 'select',
      label: 'Layout',
      options: [
        { label: 'Half (50/50 split)', value: 'half' },
        { label: 'Page grid (12-col)', value: 'grid' },
        { label: 'Banner (image below text)', value: 'banner' },
      ],
    },
    textWidth: {
      type: 'select',
      label: 'Text width (page-grid layout)',
      options: [
        { label: 'Auto', value: 'auto' },
        { label: 'XS (~315px)', value: 'xs' },
        { label: 'SM (~432px)', value: 'sm' },
        { label: 'MD (~546px)', value: 'md' },
      ],
    },
    bullets: {
      type: 'array',
      label: 'Points (bulleted list under the body)',
      arrayFields: {
        title: { type: 'text', label: 'Point title' },
        body: { type: 'textarea', label: 'Point body (optional)' },
      },
      defaultItemProps: { title: '', body: '' },
      min: 0,
      max: 12,
    },
    bulletSize: {
      type: 'select',
      label: 'Point title size',
      options: [
        { label: '20px', value: 'md' },
        { label: '24px', value: 'lg' },
      ],
    },
    bodyMaxWidth: { type: 'text', label: 'Body max width (CSS, e.g. 478px)' },
    footnote: { type: 'text', label: 'Footnote (semibold italic, under body)' },
    linkVariant: {
      type: 'select',
      label: 'Link style',
      options: [
        { label: 'Text link', value: 'link' },
        { label: 'Button', value: 'button' },
      ],
    },
    bulletMarker: {
      type: 'select',
      label: 'Point marker',
      options: [
        { label: 'Square', value: 'square' },
        { label: 'None', value: 'none' },
      ],
    },
    logos: {
      type: 'array',
      label: 'Logos (optional)',
      arrayFields: {
        src: createImageField(mediaLibraryAdapter, 'Logo image'),
        alt: { type: 'text', label: 'Alt text' },
      },
      defaultItemProps: { src: '', alt: '' },
      // Explicit 0: the strip is optional (defaultProps ships []) — declared
      // so the hardening sweep still sees a bounded array field.
      min: 0,
      max: 8,
    },
    surface: {
      type: 'select',
      label: 'Surface',
      options: [
        { label: 'Default', value: 'default' },
        { label: 'Dark', value: 'dark' },
        { label: 'Muted (soft card)', value: 'muted' },
      ],
    },
    surfaceColor: {
      type: 'text',
      label: 'Surface color (CSS, white text — optional)',
    },
  },
  defaultProps: {
    imageUrl: '',
    imageAlt: '',
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
  render: (props) => <MediaObjectWidgetRender {...props} />,
};
