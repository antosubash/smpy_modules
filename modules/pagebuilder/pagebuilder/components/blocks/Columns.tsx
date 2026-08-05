import type { ComponentConfig, Slot } from '@puckeditor/core';

export interface ColumnsProps {
  /**
   * `width` is a flex ratio, not a fraction — two columns at 1 and 2 split
   * 1/3 : 2/3. `content` is the column's own slot; it lives inside the array
   * so the number of columns stays author-controlled. A top-level slot field
   * per column would cap the block at however many we declared.
   */
  columns: { width: number; content: Slot }[];
  gap: 'sm' | 'md' | 'lg';
}

const gapClass: Record<ColumnsProps['gap'], string> = {
  sm: 'gap-2',
  md: 'gap-4',
  lg: 'gap-8',
};

export const ColumnsBlock: ComponentConfig<ColumnsProps> = {
  label: 'Columns',
  fields: {
    columns: {
      type: 'array',
      arrayFields: {
        width: { type: 'number' },
        content: { type: 'slot' },
      },
      defaultItemProps: { width: 1, content: [] },
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
    columns: [
      { width: 1, content: [] },
      { width: 1, content: [] },
    ],
    gap: 'md',
  },
  render: ({ columns, gap }) => (
    <div className={`flex flex-wrap ${gapClass[gap]} my-4`}>
      {columns.map((col, idx) => {
        // Puck hands each slot back as a component, so it has to be bound to a
        // capitalised name before it can be used as an element.
        const Content = col.content;
        return (
          // The index IS the column's identity — it's what the pre-slots zone
          // name was derived from, and what the migration maps back onto.
          // biome-ignore lint/suspicious/noArrayIndexKey: index is the column's identity
          <div key={idx} style={{ flex: col.width }} className="min-w-0">
            <Content />
          </div>
        );
      })}
    </div>
  ),
};
