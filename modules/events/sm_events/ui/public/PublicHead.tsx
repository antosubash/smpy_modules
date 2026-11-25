import { Head } from '@inertiajs/react';
import { safeJsonLd } from '../utils/jsonLd';
import type { Alternate } from './types';

type Props = {
  title: string;
  description?: string | null;
  canonical?: string | null;
  alternates?: Alternate[];
  noindex?: boolean;
  image?: string | null;
  locale: string;
  feedUrl?: string | null;
  jsonLd?: unknown;
  /** An event page: the server also writes its `twitter:*` tags, so they are rendered here too. */
  event?: boolean;
};

/** The tags the server writes into the document (`_head.py`), repeated for visits made inside
 *  the SPA. Every tag carries a `head-key` equal to the server's `data-inertia` value, so
 *  hydration replaces the server's copy instead of adding a second one (#461); a tag the server
 *  writes must be rendered here under the same key, or hydration deletes it. `<Head>` does not
 *  flatten fragments, hence the flat children. The JSON-LD is the one place a public screen sets
 *  inner HTML: a non-executable `application/ld+json` script whose text has no `<`, `>` or `&`
 *  left in it. */
export function PublicHead(p: Props) {
  return (
    <Head title={p.title}>
      {p.description ? (
        <meta head-key="description" name="description" content={p.description} />
      ) : null}
      <meta head-key="og:title" property="og:title" content={p.title} />
      {p.description ? (
        <meta head-key="og:description" property="og:description" content={p.description} />
      ) : null}
      <meta head-key="og:type" property="og:type" content="website" />
      <meta head-key="og:locale" property="og:locale" content={p.locale} />
      {p.canonical ? <meta head-key="og:url" property="og:url" content={p.canonical} /> : null}
      {p.image ? <meta head-key="og:image" property="og:image" content={p.image} /> : null}
      {p.event ? (
        <meta
          head-key="twitter:card"
          name="twitter:card"
          content={p.image ? 'summary_large_image' : 'summary'}
        />
      ) : null}
      {p.event && p.image ? (
        <meta head-key="twitter:image" name="twitter:image" content={p.image} />
      ) : null}
      {p.noindex ? <meta head-key="robots" name="robots" content="noindex,nofollow" /> : null}
      {p.canonical ? <link head-key="canonical" rel="canonical" href={p.canonical} /> : null}
      {(p.alternates ?? []).map((a) => (
        <link
          key={a.locale}
          head-key={`hreflang-${a.locale}`}
          rel="alternate"
          hrefLang={a.locale}
          href={a.url}
        />
      ))}
      {p.feedUrl ? (
        <link
          head-key="feed"
          rel="alternate"
          type="text/calendar"
          title={p.title}
          href={p.feedUrl}
        />
      ) : null}
      {p.jsonLd ? (
        <script
          head-key="json-ld"
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: escaped by safeJsonLd, never executed
          dangerouslySetInnerHTML={{ __html: safeJsonLd(p.jsonLd) }}
        />
      ) : null}
    </Head>
  );
}
