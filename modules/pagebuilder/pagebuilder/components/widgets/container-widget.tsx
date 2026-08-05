import type { ComponentConfig, Slot } from '@puckeditor/core';
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
  label: 'Container',
  fields: {
    backgroundColor: { type: 'text', label: 'Background color (CSS)' },
    padding: {
      type: 'select',
      label: 'Padding',
      options: [
        { label: 'None', value: 'none' },
        { label: 'Small', value: 'sm' },
        { label: 'Medium', value: 'md' },
        { label: 'Large', value: 'lg' },
      ],
    },
    maxWidth: {
      type: 'select',
      label: 'Max width',
      options: [
        { label: 'Small', value: 'sm' },
        { label: 'Medium', value: 'md' },
        { label: 'Large', value: 'lg' },
        { label: 'Extra Large', value: 'xl' },
        { label: '2XL', value: '2xl' },
        { label: 'Full', value: 'full' },
      ],
    },
    rounded: {
      type: 'select',
      label: 'Rounded',
      options: [
        { label: 'None', value: 'none' },
        { label: 'Medium', value: 'md' },
        { label: 'Large', value: 'lg' },
        { label: 'Extra Large', value: 'xl' },
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
