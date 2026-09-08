import { Head, usePage } from '@inertiajs/react';
import { type Data, Render } from '@puckeditor/core';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import type { SharedProps } from '@simple-module-py/ui/types';

import { getLayoutPuckConfig } from '../components/layoutPuckConfig';
import { migrateContent } from '../components/migrateContent';
import { getPuckConfig } from '../components/puckConfig';

/** One language this document also exists in, as the server resolved it. */
interface Alternate {
  locale: string;
  url: string;
}

interface Props {
  title: string;
  data: Record<string, unknown>;
  meta_description: string | null;
  og_image: string | null;
  canonical_url?: string | null;
  og_url?: string | null;
  index_in_search?: boolean;
  json_ld?: Record<string, unknown> | null;
  site_name?: string | null;
  twitter_handle?: string | null;
  locale?: string | null;
  /** Published counterparts in other languages, plus an `x-default` entry.
   *  Empty on a monolingual site, and on any page with no live translation. */
  alternates?: Alternate[];
  layout_header?: Record<string, unknown> | null;
  layout_footer?: Record<string, unknown> | null;
}

// Inline JSON-LD as a string requires the document to be safe to embed
// inside ``<script>...</script>``. ``JSON.stringify`` does not escape
// the literal sequence ``</`` (or HTML comment openers), so a value like
// ``"</script><script>alert(1)</script>"`` would break out. The replace
// runs over keys and string values alike; ``<\/`` parses identically to
// ``</`` in JSON, so the document round-trips through any consumer.
function safeJsonLd(doc: Record<string, unknown>): string {
  return JSON.stringify(doc)
    .replace(/<\/(script)/gi, '<\\/$1')
    .replace(/<!--/g, '<\\!--');
}

export default function PublicPage({
  title,
  data,
  meta_description,
  og_image,
  canonical_url,
  og_url,
  index_in_search = true,
  json_ld,
  site_name,
  twitter_handle,
  locale,
  alternates = [],
  layout_header,
  layout_footer,
}: Props) {
  const jsonLdScript = json_ld ? safeJsonLd(json_ld) : null;
  // The design pack is a site-wide branding setting: one site, one look. Its
  // CSS is scoped to a root class, applied here around the *whole* document so
  // the header and footer adopt it too — a class on the page root alone would
  // stop at <main> and leave the chrome reading as a different site.
  //
  // `designPack` is not on the published SharedProps type yet; the cast goes
  // away when the framework release carrying it lands.
  const { branding } = usePage<{ props: SharedProps }>().props as unknown as SharedProps;
  const designPack = (branding as unknown as { designPack?: string | null })?.designPack;
  // Bound once per render because each of the three `migrateContent` calls
  // below needs the same config its `<Render>` gets — migrating against a
  // different palette than the one rendering would resolve zones to slots the
  // renderer doesn't have.
  const pageConfig = getPuckConfig();
  const layoutConfig = getLayoutPuckConfig();
  return (
    <div className={designPack ? `${designPack}-root` : undefined}>
      {/* The admin shell mounts this through AuthenticatedLayout; a public page
          has no layout, so without it the configured brand colour and favicon
          stopped at the sign-in wall. The widgets' `--pb-accent` and their
          solid `bg-primary-800` surfaces read the `--primary` / ramp variables
          it writes, so this is what makes Settings → Branding reach the
          public site. */}
      <BrandingHead />
      <Head title={title}>
        {meta_description && (
          <>
            <meta name="description" content={meta_description} />
            <meta property="og:description" content={meta_description} />
          </>
        )}
        <meta property="og:title" content={title} />
        <meta property="og:type" content="website" />
        {og_url && <meta property="og:url" content={og_url} />}
        {site_name && <meta property="og:site_name" content={site_name} />}
        {og_image && (
          <>
            <meta property="og:image" content={og_image} />
            <meta name="twitter:image" content={og_image} />
          </>
        )}
        <meta name="twitter:card" content={og_image ? 'summary_large_image' : 'summary'} />
        {twitter_handle && <meta name="twitter:site" content={twitter_handle} />}
        {canonical_url && <link rel="canonical" href={canonical_url} />}
        {/* One <link> per published language, the current one included —
            hreflang sets are only honoured when every member names every
            other, this page among them. The server omits the list entirely
            below two entries, so a monolingual site emits nothing here. */}
        {alternates.map((alternate) => (
          <link
            key={alternate.locale}
            rel="alternate"
            hrefLang={alternate.locale}
            href={alternate.url}
          />
        ))}
        {locale && <meta property="og:locale" content={locale} />}
        {!index_in_search && <meta name="robots" content="noindex,nofollow" />}
        {jsonLdScript && (
          // Emitting author-composed JSON-LD is the feature. The content is
          // written by permission-holding editors and served under the CSP in
          // PagebuilderSettings.public_csp.
          // biome-ignore lint/security/noDangerouslySetInnerHtml: author-composed JSON-LD is the feature
          <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript }} />
        )}
      </Head>
      {layout_header && (
        <header data-testid="site-header">
          <Render
            config={layoutConfig}
            data={migrateContent(layout_header as unknown as Data, layoutConfig)}
          />
        </header>
      )}
      <main>
        <Render config={pageConfig} data={migrateContent(data as unknown as Data, pageConfig)} />
      </main>
      {layout_footer && (
        <footer data-testid="site-footer">
          <Render
            config={layoutConfig}
            data={migrateContent(layout_footer as unknown as Data, layoutConfig)}
          />
        </footer>
      )}
    </div>
  );
}
