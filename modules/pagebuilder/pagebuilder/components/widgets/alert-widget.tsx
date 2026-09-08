import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
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
  label: keys.pagebuilder.blocks.alert.label,
  fields: {
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    message: { type: 'textarea', label: keys.pagebuilder.blocks.alert.message },
    variant: {
      type: 'select',
      label: keys.pagebuilder.blocks.alert.variant,
      options: [
        { label: keys.pagebuilder.blocks.alert.variant_info, value: 'info' },
        { label: keys.pagebuilder.blocks.alert.variant_success, value: 'success' },
        { label: keys.pagebuilder.blocks.alert.variant_warning, value: 'warning' },
        { label: keys.pagebuilder.blocks.alert.variant_error, value: 'error' },
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
