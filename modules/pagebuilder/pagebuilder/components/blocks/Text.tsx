import type { ComponentConfig } from '@puckeditor/core';

interface TextProps {
  text: string;
  align: 'left' | 'center' | 'right';
}

export const TextBlock: ComponentConfig<TextProps> = {
  label: 'Text',
  fields: {
    text: { type: 'textarea' },
    align: {
      type: 'radio',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Center', value: 'center' },
        { label: 'Right', value: 'right' },
      ],
    },
  },
  defaultProps: { text: 'Some descriptive text.', align: 'left' },
  render: ({ text, align }) => (
    <p className={`text-${align} whitespace-pre-line leading-relaxed my-3`}>{text}</p>
  ),
};
