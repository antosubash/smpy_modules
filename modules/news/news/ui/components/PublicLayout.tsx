import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import type { ComponentType, ReactNode } from 'react';

/** Public server props are neutral: importing news never requires pagebuilder. */
export interface PublicLayoutProps {
  locale?: string;
  layout_header?: Record<string, unknown> | null;
  layout_footer?: Record<string, unknown> | null;
  site_nav?: {
    header: { label: string; href: string }[];
    footer: { label: string; href: string }[];
  } | null;
  copy?: {
    skip_to_content: string;
    not_found: { title: string; body: string; home: string };
  } | null;
}

type LayoutProps = PublicLayoutProps & { children: ReactNode };
let SiteLayout: ComponentType<LayoutProps> | undefined;

/** Called only from the optional pagebuilder entry, before any page renders. */
export function registerPublicLayout(component: ComponentType<LayoutProps>) {
  SiteLayout = component;
}

export function PublicLayout(props: LayoutProps) {
  // `copy` also signals a mounted site whose two layout slots are empty.
  if (SiteLayout && (props.copy || props.layout_header || props.layout_footer)) {
    return <SiteLayout {...props} />;
  }
  return (
    <div>
      {/* Standalone hosts keep their original branding and reading column. */}
      <BrandingHead />
      {props.children}
    </div>
  );
}
