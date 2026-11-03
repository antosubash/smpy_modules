import type { ComponentConfig, Slot } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';

export type ContainerWidgetProps = {
  backgroundColor: string;
  padding: 'none' | 'sm' | 'md' | 'lg';
  maxWidth: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'full';
  rounded: 'none' | 'md' | 'lg' | 'xl';
  container: Slot;
};

const PADDING_CLASS: Record<ContainerWidgetProps['padding'], string> = {
  none: 'p-0',
  sm: 'p-4',
  md: 'p-8',
  lg: 'p-12',
};

const MAX_WIDTH_CLASS: Record<ContainerWidgetProps['maxWidth'], string> = {
  sm: 'max-w-screen-sm',
  md: 'max-w-screen-md',
  lg: 'max-w-screen-lg',
  xl: 'max-w-screen-xl',
  '2xl': 'max-w-screen-2xl',
  full: 'max-w-full',
};

const ROUNDED_CLASS: Record<ContainerWidgetProps['rounded'], string> = {
  none: 'rounded-none',
  md: 'rounded-md',
  lg: 'rounded-lg',
  xl: 'rounded-xl',
};

export const ContainerWidget: ComponentConfig<ContainerWidgetProps> = {
  label: keys.pagebuilder.blocks.container.label,
  fields: {
    backgroundColor: { type: 'text', label: keys.pagebuilder.blocks.container.background_color },
    padding: {
      type: 'select',
      label: keys.pagebuilder.blocks.container.padding,
      options: [
        { label: keys.pagebuilder.blocks.container.padding_none, value: 'none' },
        { label: keys.pagebuilder.blocks.container.padding_sm, value: 'sm' },
        { label: keys.pagebuilder.blocks.container.padding_md, value: 'md' },
        { label: keys.pagebuilder.blocks.container.padding_lg, value: 'lg' },
      ],
    },
    maxWidth: {
      type: 'select',
      label: keys.pagebuilder.blocks.container.max_width,
      options: [
        { label: keys.pagebuilder.blocks.container.max_width_sm, value: 'sm' },
        { label: keys.pagebuilder.blocks.container.max_width_md, value: 'md' },
        { label: keys.pagebuilder.blocks.container.max_width_lg, value: 'lg' },
        { label: keys.pagebuilder.blocks.container.max_width_xl, value: 'xl' },
        { label: keys.pagebuilder.blocks.container.max_width_2xl, value: '2xl' },
        { label: keys.pagebuilder.blocks.container.max_width_full, value: 'full' },
      ],
    },
    rounded: {
      type: 'select',
      label: keys.pagebuilder.blocks.container.rounded,
      options: [
        { label: keys.pagebuilder.blocks.container.rounded_none, value: 'none' },
        { label: keys.pagebuilder.blocks.container.rounded_md, value: 'md' },
        { label: keys.pagebuilder.blocks.container.rounded_lg, value: 'lg' },
        { label: keys.pagebuilder.blocks.container.rounded_xl, value: 'xl' },
      ],
    },
    container: { type: 'slot' },
  },
  defaultProps: {
    backgroundColor: '',
    padding: 'md',
    maxWidth: 'xl',
    rounded: 'none',
    container: [],
  },
  render: ({ backgroundColor, padding, maxWidth, rounded, container: Container }) => (
    <div
      className={cn(
        'mx-auto',
        PADDING_CLASS[padding],
        MAX_WIDTH_CLASS[maxWidth],
        ROUNDED_CLASS[rounded],
      )}
      style={backgroundColor ? { backgroundColor } : undefined}
    >
      <Container />
    </div>
  ),
};
