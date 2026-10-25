import { Head } from '@inertiajs/react';
import { type Data, Render } from '@puckeditor/core';

import { migrateContent } from '../components/migrateContent';
import type { PreviewInfo } from '../components/public/PreviewBar';
import { type PublicCopy, PublicShell } from '../components/public/PublicShell';
import { getPuckConfig } from '../components/puckConfig';
import type { SiteNav } from '../components/widgets/_internal/site-nav-context';

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
  /** Pages flagged for the header / footer nav, in this page's language. */
  site_nav?: SiteNav | null;
  /** Only the admin's draft preview sends this; it shows the draft bar. */
  preview?: PreviewInfo | null;
  /** The frame's own strings, in this page's language. */
  copy?: PublicCopy | null;
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
  site_nav,
  preview,
  copy,
}: Props) {
  const jsonLdScript = json_ld ? safeJsonLd(json_ld) : null;
  // The same config its `<Render>` gets: migrating against a different
  // palette than the one rendering would resolve zones to slots the renderer
  // doesn't have. The layout's header and footer are `PublicShell`'s.
  const pageConfig = getPuckConfig();
  return (
    <PublicShell
      locale={locale}
      layout_header={layout_header}
      layout_footer={layout_footer}
      site_nav={site_nav}
      preview={preview}
      copy={copy}
    >
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
      <Render config={pageConfig} data={migrateContent(data as unknown as Data, pageConfig)} />
    </PublicShell>
  );
}
