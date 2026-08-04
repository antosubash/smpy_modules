/** Contact form widget: field definitions and config assembly.
 *  Types and render live in contact-form-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';

import { ContactFormRender, type ContactFormWidgetProps } from './contact-form-render';

export type { ContactFormWidgetProps } from './contact-form-render';

export const ContactFormWidget: ComponentConfig<ContactFormWidgetProps> = {
  label: 'Contact form',
  fields: {
    variant: {
      type: 'select',
      label: 'Style',
      options: [
        { label: 'Boxed inputs', value: 'boxed' },
        { label: 'Underline inputs (panel)', value: 'underline' },
      ],
    },
    surfaceColor: {
      type: 'text',
      label: 'Panel color (CSS, inverse text — optional)',
    },
    title: { type: 'text', label: 'Title' },
    subtitle: { type: 'textarea', label: 'Subtitle' },
    nameLabel: { type: 'text', label: 'Name field label' },
    namePlaceholder: { type: 'text', label: 'Name placeholder' },
    orgLabel: {
      type: 'text',
      label: 'Organisation field label (blank to hide)',
    },
    orgPlaceholder: { type: 'text', label: 'Organisation placeholder' },
    enquiryLabel: { type: 'text', label: 'Enquiry type label' },
    enquiryOptions: {
      type: 'textarea',
      label: 'Enquiry options (one per line)',
    },
    emailLabel: { type: 'text', label: 'Email field label' },
    emailPlaceholder: { type: 'text', label: 'Email placeholder' },
    messageLabel: { type: 'text', label: 'Message field label' },
    messagePlaceholder: { type: 'text', label: 'Message placeholder' },
    termsLabel: { type: 'text', label: 'Terms agreement label' },
    submitLabel: { type: 'text', label: 'Submit button' },
    successTitle: { type: 'text', label: 'Success title' },
    successBody: { type: 'textarea', label: 'Success body' },
  },
  defaultProps: {
    variant: 'boxed',
    surfaceColor: '',
    title: 'Contact us',
    subtitle: "We'd love to hear from you.",
    nameLabel: 'Name',
    namePlaceholder: 'Your name',
    orgLabel: 'Organisation name',
    orgPlaceholder: 'Your organisation',
    enquiryLabel: 'Enquiry type',
    enquiryOptions: 'General\nCollaborations\nData contributions\nPress & media\nScience',
    emailLabel: 'Email',
    emailPlaceholder: 'you@example.com',
    messageLabel: 'Message',
    messagePlaceholder: 'How can we help?',
    termsLabel: 'I have read and agree to the Terms and Conditions',
    submitLabel: 'Send message',
    successTitle: 'Your message has been sent',
    successBody: 'Thank you for contacting us, a team member will be in touch with you shortly',
  },
  render: (props) => <ContactFormRender {...props} />,
};
