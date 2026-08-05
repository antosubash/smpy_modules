import type { ComponentConfig } from '@puckeditor/core';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type WelcomeWidgetProps = {
  greeting: string;
  body: string;
  signature: string;
};

export const WelcomeWidget: ComponentConfig<WelcomeWidgetProps> = {
  label: 'Welcome',
  fields: {
    greeting: { type: 'text', label: 'Greeting' },
    body: { type: 'textarea', label: 'Body' },
    signature: { type: 'text', label: 'Signature' },
  },
  defaultProps: {
    greeting: 'Welcome!',
    body: "We're glad to have you here.",
    signature: 'The team',
  },
  render: ({ greeting, body, signature }) => (
    <div className="container mx-auto max-w-2xl py-12 px-4 text-center">
      <h2 className="text-3xl sm:text-4xl lg:text-5xl font-light mb-4">
        {renderRichText(greeting)}
      </h2>
      <RichTextBlock
        text={body}
        className="text-lg text-gray-700 dark:text-gray-300 leading-relaxed"
      />
      {signature && (
        <p className="mt-6 italic text-gray-500 dark:text-gray-400">
          — {renderRichText(signature)}
        </p>
      )}
    </div>
  ),
};
