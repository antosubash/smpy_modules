import type { ComponentConfig } from '@puckeditor/core';
import { cn } from '../../utils/widgetUtils';

export type DividerWidgetProps = {
  thickness: 'thin' | 'medium' | 'thick';
  style: 'solid' | 'dashed' | 'dotted';
  color: string;
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
  },
  defaultProps: {
    thickness: 'thin',
    style: 'solid',
    color: '#e5e7eb',
  },
  render: ({ thickness, style, color }) => (
    <hr
      className={cn('my-6', THICKNESS_CLASS[thickness], STYLE_CLASS[style])}
      style={{ borderColor: color }}
    />
  ),
};
