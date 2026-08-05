import type { ComponentConfig, Slot } from '@puckeditor/core';
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
  label: 'Grid',
  fields: {
    columns: {
      type: 'select',
      label: 'Columns',
      options: [
        { label: '1', value: '1' },
        { label: '2', value: '2' },
        { label: '3', value: '3' },
        { label: '4', value: '4' },
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
