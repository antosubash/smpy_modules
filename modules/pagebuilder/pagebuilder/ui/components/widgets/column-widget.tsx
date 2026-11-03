import type { ComponentConfig, Slot } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
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
  label: keys.pagebuilder.blocks.column.label,
  fields: {
    width: {
      type: 'select',
      label: keys.pagebuilder.blocks.column.width,
      options: [
        { label: keys.pagebuilder.blocks.column.width_1_4, value: '1/4' },
        { label: keys.pagebuilder.blocks.column.width_1_3, value: '1/3' },
        { label: keys.pagebuilder.blocks.column.width_1_2, value: '1/2' },
        { label: keys.pagebuilder.blocks.column.width_2_3, value: '2/3' },
        { label: keys.pagebuilder.blocks.column.width_3_4, value: '3/4' },
        { label: keys.pagebuilder.blocks.column.width_full, value: 'full' },
      ],
    },
    gap: {
      type: 'select',
      label: keys.pagebuilder.blocks.common.gap,
      options: [
        { label: keys.pagebuilder.blocks.common.gap_none, value: 'none' },
        { label: keys.pagebuilder.blocks.common.gap_sm, value: 'sm' },
        { label: keys.pagebuilder.blocks.common.gap_md, value: 'md' },
        { label: keys.pagebuilder.blocks.common.gap_lg, value: 'lg' },
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
