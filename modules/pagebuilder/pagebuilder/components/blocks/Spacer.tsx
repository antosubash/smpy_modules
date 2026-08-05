import type { ComponentConfig } from '@puckeditor/core';

interface SpacerProps {
  size: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
}

const heights: Record<SpacerProps['size'], number> = {
  xs: 8,
  sm: 16,
  md: 32,
  lg: 64,
  xl: 128,
};

export const SpacerBlock: ComponentConfig<SpacerProps> = {
  fields: {
    size: {
      type: 'select',
      options: [
        { label: 'XS', value: 'xs' },
        { label: 'S', value: 'sm' },
        { label: 'M', value: 'md' },
        { label: 'L', value: 'lg' },
        { label: 'XL', value: 'xl' },
      ],
    },
  },
  defaultProps: { size: 'md' },
  render: ({ size }) => <div style={{ height: heights[size] }} aria-hidden />,
};
