import type { ComponentConfig, Slot } from '@puckeditor/core';
import { cn } from '../../utils/widgetUtils';

export type RowWidgetProps = {
  gap: 'none' | 'sm' | 'md' | 'lg';
  align: 'start' | 'center' | 'end';
  wrap: 'wrap' | 'nowrap';
  row: Slot;
};

const GAP_CLASS: Record<RowWidgetProps['gap'], string> = {
  none: 'gap-0',
  sm: 'gap-2',
  md: 'gap-4',
  lg: 'gap-8',
};

const ALIGN_CLASS: Record<RowWidgetProps['align'], string> = {
  start: 'items-start',
  center: 'items-center',
  end: 'items-end',
};

export const RowWidget: ComponentConfig<RowWidgetProps> = {
  label: 'Row',
  fields: {
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
    align: {
      type: 'select',
      label: 'Vertical alignment',
      options: [
        { label: 'Start', value: 'start' },
        { label: 'Center', value: 'center' },
        { label: 'End', value: 'end' },
      ],
    },
    wrap: {
      type: 'select',
      label: 'Wrap',
      options: [
        { label: 'Wrap', value: 'wrap' },
        { label: 'No wrap', value: 'nowrap' },
      ],
    },
    row: { type: 'slot' },
  },
  defaultProps: {
    gap: 'md',
    align: 'start',
    wrap: 'wrap',
    row: [],
  },
  render: ({ gap, align, wrap, row: Row }) => (
    <div
      className={cn(
        'flex w-full',
        GAP_CLASS[gap],
        ALIGN_CLASS[align],
        wrap === 'wrap' ? 'flex-wrap' : 'flex-nowrap',
      )}
    >
      <Row />
    </div>
  ),
};
