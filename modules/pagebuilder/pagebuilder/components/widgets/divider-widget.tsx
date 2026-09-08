import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
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
  label: keys.pagebuilder.blocks.divider.label,
  fields: {
    thickness: {
      type: 'select',
      label: keys.pagebuilder.blocks.divider.thickness,
      options: [
        { label: keys.pagebuilder.blocks.divider.thickness_thin, value: 'thin' },
        { label: keys.pagebuilder.blocks.divider.thickness_medium, value: 'medium' },
        { label: keys.pagebuilder.blocks.divider.thickness_thick, value: 'thick' },
      ],
    },
    style: {
      type: 'select',
      label: keys.pagebuilder.blocks.divider.style,
      options: [
        { label: keys.pagebuilder.blocks.divider.style_solid, value: 'solid' },
        { label: keys.pagebuilder.blocks.divider.style_dashed, value: 'dashed' },
        { label: keys.pagebuilder.blocks.divider.style_dotted, value: 'dotted' },
      ],
    },
    color: { type: 'text', label: keys.pagebuilder.blocks.divider.color },
    maxWidth: {
      type: 'select',
      label: keys.pagebuilder.blocks.divider.max_width,
      options: MEASURE_OPTIONS,
    },
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
