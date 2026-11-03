import type { ComponentConfig, Slot } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';

export type GridWidgetProps = {
  columns: '1' | '2' | '3' | '4';
  gap: 'none' | 'sm' | 'md' | 'lg';
  grid: Slot;
};

const COLS_CLASS: Record<GridWidgetProps['columns'], string> = {
  '1': 'grid-cols-1',
  '2': 'grid-cols-1 sm:grid-cols-2',
  '3': 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
  '4': 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4',
};

const GAP_CLASS: Record<GridWidgetProps['gap'], string> = {
  none: 'gap-0',
  sm: 'gap-2',
  md: 'gap-4',
  lg: 'gap-8',
};

export const GridWidget: ComponentConfig<GridWidgetProps> = {
  label: keys.pagebuilder.blocks.grid.label,
  fields: {
    columns: {
      type: 'select',
      label: keys.pagebuilder.blocks.grid.columns,
      options: [
        { label: keys.pagebuilder.blocks.grid.columns_1, value: '1' },
        { label: keys.pagebuilder.blocks.grid.columns_2, value: '2' },
        { label: keys.pagebuilder.blocks.grid.columns_3, value: '3' },
        { label: keys.pagebuilder.blocks.grid.columns_4, value: '4' },
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
    grid: { type: 'slot' },
  },
  defaultProps: {
    columns: '3',
    gap: 'md',
    grid: [],
  },
  render: ({ columns, gap, grid: Grid }) => (
    <div className={cn('grid', COLS_CLASS[columns], GAP_CLASS[gap])}>
      <Grid />
    </div>
  ),
};
