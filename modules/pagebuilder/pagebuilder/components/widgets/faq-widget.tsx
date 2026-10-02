/** FAQ widget: field definitions and config assembly.
 *  Types, styles and render live in faq-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
import { FaqRender, type FaqWidgetProps } from './faq-render';

export type { FaqItem, FaqWidgetProps } from './faq-render';

export const FaqWidget: ComponentConfig<FaqWidgetProps> = {
  label: keys.pagebuilder.blocks.faq.label,
  fields: {
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.faq.eyebrow },
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    lead: { type: 'textarea', label: keys.pagebuilder.blocks.faq.lead },
    variant: {
      type: 'select',
      label: keys.pagebuilder.blocks.faq.variant,
      options: [
        { label: keys.pagebuilder.blocks.faq.variant_cards, value: 'cards' },
        { label: keys.pagebuilder.blocks.faq.variant_divider, value: 'divider' },
      ],
    },
    surface: {
      type: 'select',
      label: keys.pagebuilder.blocks.faq.surface,
      options: [
        { label: keys.pagebuilder.blocks.faq.surface_default, value: 'default' },
        { label: keys.pagebuilder.blocks.faq.surface_muted, value: 'muted' },
      ],
    },
    surfaceColor: {
      type: 'text',
      label: keys.pagebuilder.blocks.common.surface_color,
    },
    items: {
      type: 'array',
      label: keys.pagebuilder.blocks.faq.items,
      arrayFields: {
        question: { type: 'text', label: keys.pagebuilder.blocks.faq.items_question },
        answer: { type: 'textarea', label: keys.pagebuilder.blocks.faq.items_answer },
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
