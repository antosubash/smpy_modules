/** FAQ widget: field definitions and config assembly.
 *  Types, styles and render live in faq-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import { FaqRender, type FaqWidgetProps } from './faq-render';

export type { FaqItem, FaqWidgetProps } from './faq-render';

export const FaqWidget: ComponentConfig<FaqWidgetProps> = {
  label: 'FAQ',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow (enables 2-column layout)' },
    title: { type: 'text', label: 'Title' },
    lead: { type: 'textarea', label: 'Lead paragraph (2-column layout)' },
    variant: {
      type: 'select',
      label: 'Style',
      options: [
        { label: 'Cards', value: 'cards' },
        { label: 'Divider rows', value: 'divider' },
      ],
    },
    surface: {
      type: 'select',
      label: 'Surface (2-column layout)',
      options: [
        { label: 'Default', value: 'default' },
        { label: 'Muted (soft card)', value: 'muted' },
      ],
    },
    surfaceColor: {
      type: 'text',
      label: 'Surface color (CSS, white text — optional)',
    },
    items: {
      type: 'array',
      label: 'Questions',
      arrayFields: {
        question: { type: 'text', label: 'Question' },
        answer: { type: 'textarea', label: 'Answer' },
      },
      defaultItemProps: {
        question: 'Your question?',
        answer: 'The answer goes here.',
      },
      min: 1,
      max: 30,
    },
  },
  defaultProps: {
    eyebrow: '',
    title: 'Frequently asked questions',
    lead: '',
    variant: 'cards',
    surface: 'default',
    surfaceColor: '',
    items: [
      { question: 'How does this work?', answer: 'It just does.' },
      { question: 'Is it free?', answer: "There's a free plan." },
    ],
  },
  render: (props) => <FaqRender {...props} />,
};
