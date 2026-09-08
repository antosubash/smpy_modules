import type { ComponentConfig, Slot } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
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
  label: keys.pagebuilder.blocks.row.label,
  fields: {
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
    align: {
      type: 'select',
      label: keys.pagebuilder.blocks.row.align,
      options: [
        { label: keys.pagebuilder.blocks.row.align_start, value: 'start' },
        { label: keys.pagebuilder.blocks.row.align_center, value: 'center' },
        { label: keys.pagebuilder.blocks.row.align_end, value: 'end' },
      ],
    },
    wrap: {
      type: 'select',
      label: keys.pagebuilder.blocks.row.wrap,
      options: [
        { label: keys.pagebuilder.blocks.row.wrap_wrap, value: 'wrap' },
        { label: keys.pagebuilder.blocks.row.wrap_nowrap, value: 'nowrap' },
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
