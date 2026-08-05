/** TimelineWidget: field definitions and config assembly.
 *  Types live in timeline-layout.ts, render in timeline-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import type { TimelineWidgetProps } from './timeline-layout';
import { TimelineWidgetRender } from './timeline-render';

export type * from './timeline-layout';

export const TimelineWidget: ComponentConfig<TimelineWidgetProps> = {
  label: 'Timeline',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow' },
    title: { type: 'text', label: 'Title' },
    surface: {
      type: 'select',
      label: 'Surface',
      options: [
        { label: 'Default', value: 'default' },
        { label: 'Muted (soft card)', value: 'muted' },
      ],
    },
    variant: {
      type: 'select',
      label: 'Variant',
      options: [
        { label: 'Rows (list)', value: 'rows' },
        { label: 'Blobs (organic shapes)', value: 'blobs' },
      ],
    },
    blobMaskUrl: {
      type: 'text',
      label: 'Blob mask URL (organic shape — blobs variant)',
    },
    markerMaskUrl: {
      type: 'text',
      label: 'Marker mask URL (organic tag shape — blobs variant)',
    },
    markerImageUrl: {
      type: 'text',
      label: 'Marker artwork (transparent PNG — replaces mask + colour)',
    },
    markerColor: {
      type: 'text',
      label: 'Marker color (CSS — blobs variant)',
    },
    items: {
      type: 'array',
      label: 'Entries',
      arrayFields: {
        marker: { type: 'text', label: 'Marker (e.g. year)' },
        title: { type: 'text', label: 'Title' },
        body: { type: 'textarea', label: 'Body' },
        meta: { type: 'text', label: 'Trailing line (e.g. date)' },
        color: { type: 'text', label: 'Blob color (CSS — blobs variant)' },
        shapeMaskUrl: {
          type: 'text',
          label: 'Blob shape mask URL (overrides the section mask)',
        },
        shapeImageUrl: {
          type: 'text',
          label: 'Blob artwork (transparent PNG — replaces mask + colour)',
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
