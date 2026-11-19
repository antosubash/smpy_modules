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
};

/** The tags the server writes into the document (`_head.py`), repeated for visits made inside
 *  the SPA. The JSON-LD is the one place a public screen sets inner HTML: a non-executable
 *  `application/ld+json` script whose text has no `<`, `>` or `&` left in it. */
export function PublicHead(p: Props) {
  return (
    <Head title={p.title}>
      {p.description ? <meta name="description" content={p.description} /> : null}
      <meta property="og:title" content={p.title} />
      {p.description ? <meta property="og:description" content={p.description} /> : null}
      <meta property="og:type" content="website" />
      <meta property="og:locale" content={p.locale} />
      {p.canonical ? <meta property="og:url" content={p.canonical} /> : null}
      {p.image ? <meta property="og:image" content={p.image} /> : null}
      {p.noindex ? <meta name="robots" content="noindex,nofollow" /> : null}
      {p.canonical ? <link rel="canonical" href={p.canonical} /> : null}
      {(p.alternates ?? []).map((a) => (
        <link key={a.locale} rel="alternate" hrefLang={a.locale} href={a.url} />
      ))}
      {p.feedUrl ? (
        <link rel="alternate" type="text/calendar" title={p.title} href={p.feedUrl} />
      ) : null}
      {p.jsonLd ? (
        <script
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: escaped by safeJsonLd, never executed
          dangerouslySetInnerHTML={{ __html: safeJsonLd(p.jsonLd) }}
        />
      ) : null}
    </Head>
  );
}
