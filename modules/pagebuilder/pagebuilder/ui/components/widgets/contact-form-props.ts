export type ContactFormWidgetProps = {
  variant: 'boxed' | 'underline';
  /**
   * Optional CSS color for the form panel. When set, the panel renders on that
   * color with inverse (white) labels, underline fields and an outline pill
   * submit; blank keeps the default grey panel.
   */
  surfaceColor: string;
  title: string;
  subtitle: string;
  nameLabel: string;
  namePlaceholder: string;
  orgLabel: string;
  orgPlaceholder: string;
  enquiryLabel: string;
  enquiryOptions: string;
  emailLabel: string;
  emailPlaceholder: string;
  messageLabel: string;
  messagePlaceholder: string;
  termsLabel: string;
  submitLabel: string;
  successTitle: string;
  successBody: string;
};
