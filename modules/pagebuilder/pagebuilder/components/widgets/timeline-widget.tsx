/** TimelineWidget: field definitions and config assembly.
 *  Types live in timeline-layout.ts, render in timeline-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
import type { TimelineWidgetProps } from './timeline-layout';
import { TimelineWidgetRender } from './timeline-render';

export type * from './timeline-layout';

export const TimelineWidget: ComponentConfig<TimelineWidgetProps> = {
  label: keys.pagebuilder.blocks.timeline.label,
  fields: {
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.timeline.eyebrow },
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    surface: {
      type: 'select',
      label: keys.pagebuilder.blocks.timeline.surface,
      options: [
        { label: keys.pagebuilder.blocks.timeline.surface_default, value: 'default' },
        { label: keys.pagebuilder.blocks.timeline.surface_muted, value: 'muted' },
      ],
    },
    variant: {
      type: 'select',
      label: keys.pagebuilder.blocks.timeline.variant,
      options: [
        { label: keys.pagebuilder.blocks.timeline.variant_rows, value: 'rows' },
        { label: keys.pagebuilder.blocks.timeline.variant_blobs, value: 'blobs' },
      ],
    },
    blobMaskUrl: {
      type: 'text',
      label: keys.pagebuilder.blocks.timeline.blob_mask_url,
    },
    markerMaskUrl: {
      type: 'text',
      label: keys.pagebuilder.blocks.timeline.marker_mask_url,
    },
    markerImageUrl: {
      type: 'text',
      label: keys.pagebuilder.blocks.timeline.marker_image_url,
    },
    markerColor: {
      type: 'text',
      label: keys.pagebuilder.blocks.timeline.marker_color,
    },
    items: {
      type: 'array',
      label: keys.pagebuilder.blocks.timeline.items,
      arrayFields: {
        marker: { type: 'text', label: keys.pagebuilder.blocks.timeline.items_marker },
        title: { type: 'text', label: keys.pagebuilder.blocks.timeline.items_title },
        body: { type: 'textarea', label: keys.pagebuilder.blocks.timeline.items_body },
        meta: { type: 'text', label: keys.pagebuilder.blocks.timeline.items_meta },
        color: { type: 'text', label: keys.pagebuilder.blocks.timeline.items_color },
        shapeMaskUrl: {
          type: 'text',
          label: keys.pagebuilder.blocks.timeline.items_shape_mask_url,
        },
        shapeImageUrl: {
          type: 'text',
          label: keys.pagebuilder.blocks.timeline.items_shape_image_url,
        },
      },
      defaultItemProps: {
        marker: '2026',
        title: 'Milestone',
        body: '',
        meta: '',
        color: '',
        shapeMaskUrl: '',
        shapeImageUrl: '',
      },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    eyebrow: '',
    title: 'Incentives & Recognition',
    surface: 'default',
    variant: 'rows',
    blobMaskUrl: '',
    markerMaskUrl: '',
    markerImageUrl: '',
    markerColor: '',
    items: [
      {
        marker: '2026',
        title: 'Scientific Co-Authorship',
        body: 'In the current year (2026) at the end of the project, the top data contributors will be invited to co-write and become co-authors in a data descriptor paper that will be submitted to a scientific journal.',
      },
      {
        marker: '2027',
        title: 'Additional Incentives',
        body: 'In the next year (2027) the pilot project will include additionally some basic incentives for participants providing large quantities of high-quality quests.',
      },
    ],
  },
  // Column geometry is tenant-tunable via `--pb-split-cols`/`--pb-split-gap`
  // (Mowing aligns the content to the 4th page-grid column) and the content is
  // capped by `--pb-split-content-max` (Mowing → 774px per the Figma); the
  // fallbacks keep tenants without the tokens on the prior layout.
  render: TimelineWidgetRender,
};
