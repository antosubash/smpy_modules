import { type ComponentConfig, DropZone } from '@measured/puck';

interface ColumnsProps {
  columns: { width: number }[];
  gap: 'sm' | 'md' | 'lg';
}

const gapClass: Record<ColumnsProps['gap'], string> = {
  sm: 'gap-2',
  md: 'gap-4',
  lg: 'gap-8',
};

export const ColumnsBlock: ComponentConfig<ColumnsProps> = {
  fields: {
    columns: {
      type: 'array',
      arrayFields: {
        width: { type: 'number' },
      },
      defaultItemProps: { width: 1 },
    },
    gap: {
      type: 'select',
      options: [
        { label: 'Small', value: 'sm' },
        { label: 'Medium', value: 'md' },
        { label: 'Large', value: 'lg' },
      ],
    },
  },
  defaultProps: {
    columns: [{ width: 1 }, { width: 1 }],
    gap: 'md',
  },
  render: ({ columns, gap }) => (
    <div className={`flex flex-wrap ${gapClass[gap]} my-4`}>
      {columns.map((col, idx) => (
        <div key={idx} style={{ flex: col.width }} className="min-w-0">
          <DropZone zone={`col-${idx}`} />
        </div>
      ))}
    </div>
  ),
};
