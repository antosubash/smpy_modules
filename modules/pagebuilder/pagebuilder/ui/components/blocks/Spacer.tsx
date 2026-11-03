import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';

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
  label: keys.pagebuilder.blocks.spacer.label,
  fields: {
    size: {
      type: 'select',
      options: [
        { label: keys.pagebuilder.blocks.spacer.size_xs, value: 'xs' },
        { label: keys.pagebuilder.blocks.spacer.size_sm, value: 'sm' },
        { label: keys.pagebuilder.blocks.spacer.size_md, value: 'md' },
        { label: keys.pagebuilder.blocks.spacer.size_lg, value: 'lg' },
        { label: keys.pagebuilder.blocks.spacer.size_xl, value: 'xl' },
      ],
    },
  },
  defaultProps: { size: 'md' },
  render: ({ size }) => <div style={{ height: heights[size] }} aria-hidden />,
};
