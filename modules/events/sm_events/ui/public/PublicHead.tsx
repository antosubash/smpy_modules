import { Head } from '@inertiajs/react';
import { safeJsonLd } from '../utils/jsonLd';
import type { Alternate, HeadValues } from './types';

type Props = {
  head: HeadValues;
  locale: string;
  alternates?: Alternate[];
  jsonLd?: unknown;
  /** An event page: the server also writes its `twitter:*` tags, so they are rendered here too. */
  event?: boolean;
};

/** The tags the server writes into the document (`_head.py`), rendered from the same values
 *  (`head`, resolved once by the endpoint), so each keyed tag hydrates into an equal one. Every
 *  tag carries a `head-key` equal to the server's `data-inertia` value (#461); a tag the server
 *  writes must be rendered here under the same key, or hydration deletes it. `<Head>` does not
 *  flatten fragments, hence the flat children. The JSON-LD is the one place a public screen sets
 *  inner HTML: a non-executable `application/ld+json` script whose text has no `<`, `>` or `&`
 *  left in it. */
export function PublicHead({ head, locale, alternates = [], jsonLd, event }: Props) {
  const { title, description, canonical, image, robots, feed_url: feedUrl } = head;
  return (
    <Head title={title}>
      {description ? (
        <meta head-key="description" name="description" content={description} />
      ) : null}
      <meta head-key="og:title" property="og:title" content={title} />
      {description ? (
        <meta head-key="og:description" property="og:description" content={description} />
      ) : null}
      <meta head-key="og:type" property="og:type" content="website" />
      <meta head-key="og:locale" property="og:locale" content={locale} />
      {canonical ? <meta head-key="og:url" property="og:url" content={canonical} /> : null}
      {image ? <meta head-key="og:image" property="og:image" content={image} /> : null}
      {event ? (
        <meta
          head-key="twitter:card"
          name="twitter:card"
          content={image ? 'summary_large_image' : 'summary'}
        />
      ) : null}
      {event && image ? (
        <meta head-key="twitter:image" name="twitter:image" content={image} />
      ) : null}
      {robots ? <meta head-key="robots" name="robots" content={robots} /> : null}
      {canonical ? <link head-key="canonical" rel="canonical" href={canonical} /> : null}
      {alternates.map((a) => (
        <link
          key={a.locale}
          head-key={`hreflang-${a.locale}`}
          rel="alternate"
          hrefLang={a.locale}
          href={a.url}
        />
      ))}
      {feedUrl ? (
        <link head-key="feed" rel="alternate" type="text/calendar" title={title} href={feedUrl} />
      ) : null}
      {jsonLd ? (
        <script
          head-key="json-ld"
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: escaped by safeJsonLd, never executed
          dangerouslySetInnerHTML={{ __html: safeJsonLd(jsonLd) }}
        />
      ) : null}
    </Head>
  );
}
