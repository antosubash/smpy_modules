/** Contact form widget: field definitions and config assembly.
 *  Types and render live in contact-form-render.tsx. */

import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
import { ContactFormRender, type ContactFormWidgetProps } from './contact-form-render';

export type { ContactFormWidgetProps } from './contact-form-render';

export const ContactFormWidget: ComponentConfig<ContactFormWidgetProps> = {
  label: keys.pagebuilder.blocks.contact_form.label,
  fields: {
    variant: {
      type: 'select',
      label: keys.pagebuilder.blocks.contact_form.variant,
      options: [
        { label: keys.pagebuilder.blocks.contact_form.variant_boxed, value: 'boxed' },
        { label: keys.pagebuilder.blocks.contact_form.variant_underline, value: 'underline' },
      ],
    },
    surfaceColor: {
      type: 'text',
      label: keys.pagebuilder.blocks.contact_form.surface_color,
    },
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    subtitle: { type: 'textarea', label: keys.pagebuilder.blocks.common.subtitle },
    nameLabel: { type: 'text', label: keys.pagebuilder.blocks.contact_form.name_label },
    namePlaceholder: { type: 'text', label: keys.pagebuilder.blocks.contact_form.name_placeholder },
    orgLabel: {
      type: 'text',
      label: keys.pagebuilder.blocks.contact_form.org_label,
    },
    orgPlaceholder: { type: 'text', label: keys.pagebuilder.blocks.contact_form.org_placeholder },
    enquiryLabel: { type: 'text', label: keys.pagebuilder.blocks.contact_form.enquiry_label },
    enquiryOptions: {
      type: 'textarea',
      label: keys.pagebuilder.blocks.contact_form.enquiry_options,
    },
    emailLabel: { type: 'text', label: keys.pagebuilder.blocks.contact_form.email_label },
    emailPlaceholder: {
      type: 'text',
      label: keys.pagebuilder.blocks.contact_form.email_placeholder,
    },
    messageLabel: { type: 'text', label: keys.pagebuilder.blocks.contact_form.message_label },
    messagePlaceholder: {
      type: 'text',
      label: keys.pagebuilder.blocks.contact_form.message_placeholder,
    },
    termsLabel: { type: 'text', label: keys.pagebuilder.blocks.contact_form.terms_label },
    submitLabel: { type: 'text', label: keys.pagebuilder.blocks.contact_form.submit_label },
    successTitle: { type: 'text', label: keys.pagebuilder.blocks.contact_form.success_title },
    successBody: { type: 'textarea', label: keys.pagebuilder.blocks.contact_form.success_body },
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
