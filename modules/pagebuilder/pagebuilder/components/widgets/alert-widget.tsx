import type { ComponentConfig } from '@puckeditor/core';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type AlertWidgetProps = {
  title: string;
  message: string;
  variant: 'info' | 'success' | 'warning' | 'error';
};

const VARIANT_CLASS: Record<AlertWidgetProps['variant'], string> = {
  info: 'bg-primary-50 border-primary-200 text-primary-900',
  success: 'bg-green-50 border-green-200 text-green-900',
  warning: 'bg-yellow-50 border-yellow-200 text-yellow-900',
  error: 'bg-red-50 border-red-200 text-red-900',
};

export const AlertWidget: ComponentConfig<AlertWidgetProps> = {
  label: 'Alert',
  fields: {
    title: { type: 'text', label: 'Title' },
    message: { type: 'textarea', label: 'Message' },
    variant: {
      type: 'select',
      label: 'Variant',
      options: [
        { label: 'Info', value: 'info' },
        { label: 'Success', value: 'success' },
        { label: 'Warning', value: 'warning' },
        { label: 'Error', value: 'error' },
      ],
    },
  },
  defaultProps: {
    title: 'Heads up!',
    message: 'Something important to share.',
    variant: 'info',
  },
  render: ({ title, message, variant }) => (
    <div
      className={`max-w-3xl mx-auto rounded-lg border px-4 py-3 ${VARIANT_CLASS[variant]}`}
      role="alert"
    >
      <div className="font-semibold">{renderRichText(title || '')}</div>
      {message && <RichTextBlock text={message} className="mt-1 text-sm" />}
    </div>
  ),
};
