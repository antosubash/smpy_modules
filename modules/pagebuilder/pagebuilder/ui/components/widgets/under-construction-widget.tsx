import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
import { renderRichText } from './_internal/rich-text';

export type UnderConstructionWidgetProps = {
  message: string;
};

export const UnderConstructionWidget: ComponentConfig<UnderConstructionWidgetProps> = {
  label: keys.pagebuilder.blocks.under_construction.label,
  fields: {
    message: { type: 'text', label: keys.pagebuilder.blocks.under_construction.message },
  },
  defaultProps: {
    message: 'This section is under construction.',
  },
  render: ({ message }) => (
    <div className="container mx-auto px-4">
      <div className="max-w-xl mx-auto py-12 px-6 text-center border-2 border-dashed border-yellow-400 rounded-xl bg-yellow-50 dark:bg-yellow-950/30">
        <svg
          className="size-10 mx-auto mb-3 text-yellow-600 dark:text-yellow-400"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <title>Under construction</title>
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
          />
        </svg>
        <p className="text-yellow-900 dark:text-yellow-100 font-medium">
          {renderRichText(message)}
        </p>
      </div>
    </div>
  ),
};
