import { Head } from '@inertiajs/react';

import { type PublicCopy, PublicShell } from '../components/public/PublicShell';
import type { SiteNav } from '../components/widgets/_internal/site-nav-context';
import { keys, useT } from '../utils/i18n';

interface Props {
  locale?: string | null;
  /** The site root to send a visitor back to. */
  home_href?: string;
  site_name?: string | null;
  /** The page's strings in the address's language (`public_copy.py`). */
  copy?: PublicCopy | null;
  /** Null when the request resolved no tenant: there is no site to frame it. */
  layout_header?: Record<string, unknown> | null;
  layout_footer?: Record<string, unknown> | null;
  site_nav?: SiteNav | null;
}

/**
 * The public site's 404 (#89): one page for a missing, unpublished, trashed or
 * not-yet-live address, so it says nothing about which. Framed by the site's
 * own header and footer, branding and design pack through `PublicShell`, so a
 * visitor who mistyped an address is still on the same site.
 *
 * It speaks the address's language (`/de/p/x` is German) from the server's
 * `copy`, falling back to the UI catalogue. The home link takes the brand's
 * button colours (`bg-primary`), the way the widgets adopt it.
 */
export default function PublicNotFound({
  locale,
  home_href = '/',
  site_name,
  copy,
  layout_header,
  layout_footer,
  site_nav,
}: Props) {
  const { t } = useT();
  const words = copy?.not_found ?? {
    title: t(keys.pagebuilder.public.not_found.title),
    body: t(keys.pagebuilder.public.not_found.body),
    home: t(keys.pagebuilder.public.not_found.home),
  };
  return (
    <PublicShell
      locale={locale}
      layout_header={layout_header}
      layout_footer={layout_footer}
      site_nav={site_nav}
      copy={copy}
    >
      <Head title={site_name ? `${words.title} · ${site_name}` : words.title}>
        <meta name="robots" content="noindex" />
      </Head>
      <section
        data-testid="public-not-found"
        className="mx-auto flex max-w-xl flex-col items-center px-4 py-24 text-center sm:py-32"
      >
        <p className="font-semibold text-primary text-sm tracking-widest">404</p>
        <h1 className="mt-3 text-balance font-bold text-3xl tracking-tight sm:text-4xl">
          {words.title}
        </h1>
        <p className="mt-4 text-pretty text-base opacity-80">{words.body}</p>
        {/* A plain anchor: the site root may not be an Inertia page. */}
        <a
          href={home_href}
          className="mt-8 inline-flex items-center rounded-md bg-primary px-5 py-2.5 font-medium text-primary-foreground text-sm shadow-sm hover:opacity-90 focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2"
        >
          {words.home}
        </a>
      </section>
    </PublicShell>
  );
}
