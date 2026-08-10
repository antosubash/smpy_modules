import type { ComponentConfig } from '@puckeditor/core';
import { MEASURE_OPTIONS, type Measure, measureClass } from '../../utils/measure';
import { cn } from '../../utils/widgetUtils';

export type DividerWidgetProps = {
  thickness: 'thin' | 'medium' | 'thick';
  style: 'solid' | 'dashed' | 'dotted';
  color: string;
  /** Divider brings no container of its own, so on a `full` page root the rule
   *  spans the viewport rather than closing the section above it. */
  maxWidth: Measure;
};

const THICKNESS_CLASS: Record<DividerWidgetProps['thickness'], string> = {
  thin: 'border-t',
  medium: 'border-t-2',
  thick: 'border-t-4',
};

const STYLE_CLASS: Record<DividerWidgetProps['style'], string> = {
  solid: 'border-solid',
  dashed: 'border-dashed',
  dotted: 'border-dotted',
};

export const DividerWidget: ComponentConfig<DividerWidgetProps> = {
  label: 'Divider',
  fields: {
    thickness: {
      type: 'select',
      label: 'Thickness',
      options: [
        { label: 'Thin', value: 'thin' },
        { label: 'Medium', value: 'medium' },
        { label: 'Thick', value: 'thick' },
      ],
    },
    style: {
      type: 'select',
      label: 'Style',
      options: [
        { label: 'Solid', value: 'solid' },
        { label: 'Dashed', value: 'dashed' },
        { label: 'Dotted', value: 'dotted' },
      ],
    },
    color: { type: 'text', label: 'Color (CSS value)' },
    maxWidth: { type: 'select', label: 'Max width', options: MEASURE_OPTIONS },
  },
  defaultProps: {
    thickness: 'thin',
    style: 'solid',
    color: '#e5e7eb',
    // Full width is what every already-published Divider renders at.
    maxWidth: 'full',
  },
  render: ({ thickness, style, color, maxWidth }) => (
    <hr
      className={cn('my-6', THICKNESS_CLASS[thickness], STYLE_CLASS[style], measureClass(maxWidth))}
      style={{ borderColor: color }}
    />
  ),
};
