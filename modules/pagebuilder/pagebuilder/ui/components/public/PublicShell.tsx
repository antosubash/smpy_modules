import { usePage } from '@inertiajs/react';
import { type Data, Render } from '@puckeditor/core';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import type { SharedProps } from '@simple-module-py/ui/types';
import type { ReactNode } from 'react';

import { useDocumentLang } from '../../hooks/useDocumentLang';
import { keys, useT } from '../../utils/i18n';
import { getLayoutPuckConfig } from '../layoutPuckConfig';
import { migrateContent } from '../migrateContent';
import { type SiteNav, SiteNavProvider } from '../widgets/_internal/site-nav-context';
import { PREVIEW_BAR_HEIGHT, PreviewBar, type PreviewInfo } from './PreviewBar';
import './print.css';

export interface PublicShellProps {
  locale?: string | null;
  layout_header?: Record<string, unknown> | null;
  layout_footer?: Record<string, unknown> | null;
  /** Pages flagged for the header / footer nav, in this document's language. */
  site_nav?: SiteNav | null;
  /** Set only by the admin's draft preview. */
  preview?: PreviewInfo | null;
  /** The frame's strings in the page's language (`public_copy.py`). */
  copy?: PublicCopy | null;
  children: ReactNode;
}

/** The public frame's words, in the *content* locale rather than the UI one:
 * `/de/p/x` speaks German to a visitor whose browser says English. Absent
 * (an older server), the UI catalogue answers instead. */
export interface PublicCopy {
  skip_to_content: string;
  not_found: { title: string; body: string; home: string };
}

/** The document's own address, printed in place of the site chrome. Built
 * from Inertia's page `url`, which changes with every visit and re-renders
 * this, rather than read once from `window.location`. */
function absoluteUrl(path: string): string {
  return typeof window === 'undefined' ? path : new URL(path, window.location.origin).href;
}

/**
 * The one frame around everything the public site shows: a page, its draft
 * preview, and the not-found page (#89). Shared so the three cannot drift — a
 * 404 that framed itself differently would read as a different site.
 *
 * - Branding and the design pack apply around the *whole* document, so the
 *   header and footer adopt them too.
 * - A skip link is the first thing a keyboard reaches, and `<main>` is its
 *   focusable target.
 * - A full-height column keeps the footer at the bottom of a short page.
 * - `print.css` drops the chrome from a printout.
 *
 * Author content is rendered exactly as before; only the frame is new.
 */
export function PublicShell({
  locale,
  layout_header,
  layout_footer,
  site_nav,
  preview,
  copy,
  children,
}: PublicShellProps) {
  const { t } = useT();
  // The server writes `<html lang>` for a fresh document; this covers an
  // Inertia visit between languages, which keeps the old shell (#187).
  useDocumentLang(locale ?? undefined);
  // The design pack is a site-wide branding setting: one site, one look. Its
  // CSS is scoped to a root class, applied here around the *whole* document so
  // the header and footer adopt it too — a class on the page root alone would
  // stop at <main> and leave the chrome reading as a different site.
  //
  // `designPack` is not on the published SharedProps type yet; the cast goes
  // away when the framework release carrying it lands.
  const inertiaPage = usePage<{ props: SharedProps }>();
  const { branding } = inertiaPage.props as unknown as SharedProps;
  const designPack = (branding as unknown as { designPack?: string | null })?.designPack;
  const layoutConfig = getLayoutPuckConfig();
  const rootClass = ['pb-public flex min-h-dvh flex-col', designPack && `${designPack}-root`]
    .filter(Boolean)
    .join(' ');
  return (
    <div className={rootClass}>
      {/* The admin shell mounts this through AuthenticatedLayout; a public page
          has no layout, so without it the configured brand colour and favicon
          stopped at the sign-in wall. The widgets' `--pb-accent` and their
          solid `bg-primary-800` surfaces read the `--primary` / ramp variables
          it writes, so this is what makes Settings → Branding reach the
          public site. */}
      <BrandingHead />
      {/* Off-screen until focused rather than `sr-only`: a screen reader still
          announces it, and nothing flips its position on focus. */}
      <a
        href="#main"
        className="pb-skip fixed top-3 left-3 z-[70] -translate-y-[200%] rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground ring-2 ring-primary ring-offset-2 focus:translate-y-0"
      >
        {copy?.skip_to_content ?? t(keys.pagebuilder.public.skip_to_content)}
      </a>
      {preview && <PreviewBar preview={preview} />}
      <SiteNavProvider nav={site_nav}>
        {layout_header && (
          // A sticky header sits below the preview bar rather than under it;
          // the inline `top` outranks the stylesheet's `top: 0`.
          <header
            data-testid="site-header"
            style={preview ? { top: PREVIEW_BAR_HEIGHT } : undefined}
          >
            <Render
              config={layoutConfig}
              data={migrateContent(layout_header as unknown as Data, layoutConfig)}
            />
          </header>
        )}
        <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
          {/* A draft's URL is the private admin one; print none rather than leak it. */}
          {!preview && <p className="pb-print-url">{absoluteUrl(inertiaPage.url ?? '')}</p>}
          {children}
        </main>
        {layout_footer && (
          <footer data-testid="site-footer">
            <Render
              config={layoutConfig}
              data={migrateContent(layout_footer as unknown as Data, layoutConfig)}
            />
          </footer>
        )}
      </SiteNavProvider>
    </div>
  );
}
