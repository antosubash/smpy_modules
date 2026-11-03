export type CtaLink = { label: string; href: string };
export type CtaImage = { src: string; alt: string; caption: string };

export type CallToActionWidgetProps = {
  surface: 'default' | 'lime' | 'soft' | 'related';
  /**
   * Optional CSS color for the band background (e.g. a tenant's program
   * color). When set, renders the centered band on this color with white
   * text, overriding `surface`.
   */
  surfaceColor?: string;
  align: 'left' | 'center';
  eyebrow: string;
  heading: string;
  subheading: string;
  primaryLabel: string;
  primaryHref: string;
  secondaryLabel: string;
  secondaryHref: string;
  links: CtaLink[];
  images: CtaImage[];
};
