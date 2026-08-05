import type { ComponentConfig, Slot } from '@puckeditor/core';
import { cn } from '../../utils/widgetUtils';

export type ColumnWidgetProps = {
  width: '1/4' | '1/3' | '1/2' | '2/3' | '3/4' | 'full';
  gap: 'none' | 'sm' | 'md' | 'lg';
  column: Slot;
};

const WIDTH_CLASS: Record<ColumnWidgetProps['width'], string> = {
  '1/4': 'w-full md:w-1/4',
  '1/3': 'w-full md:w-1/3',
  '1/2': 'w-full md:w-1/2',
  '2/3': 'w-full md:w-2/3',
  '3/4': 'w-full md:w-3/4',
  full: 'w-full',
};

const GAP_CLASS: Record<ColumnWidgetProps['gap'], string> = {
  none: 'gap-0',
  sm: 'gap-2',
  md: 'gap-4',
  lg: 'gap-8',
};

export const ColumnWidget: ComponentConfig<ColumnWidgetProps> = {
  label: 'Column',
  fields: {
    width: {
      type: 'select',
      label: 'Width',
      options: [
        { label: 'Quarter', value: '1/4' },
        { label: 'Third', value: '1/3' },
        { label: 'Half', value: '1/2' },
        { label: 'Two thirds', value: '2/3' },
        { label: 'Three quarters', value: '3/4' },
        { label: 'Full', value: 'full' },
      ],
    },
    gap: {
      type: 'select',
      label: 'Gap',
      options: [
        { label: 'None', value: 'none' },
        { label: 'Small', value: 'sm' },
        { label: 'Medium', value: 'md' },
        { label: 'Large', value: 'lg' },
      ],
    },
    column: { type: 'slot' },
  },
  defaultProps: {
    width: '1/2',
    gap: 'md',
    column: [],
  },
  render: ({ width, gap, column: Column }) => (
    <div className={cn('flex flex-col', WIDTH_CLASS[width], GAP_CLASS[gap])}>
      <Column />
    </div>
  ),
};
