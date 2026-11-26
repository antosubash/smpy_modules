import { Head } from '@inertiajs/react';
import { safeJsonLd } from '../utils/jsonLd';
import type { Alternate } from './LanguageSwitch';

/** Resolved once by the endpoint and also used for its server HTML. */
export interface PublicHeadValues {
  title: string;
  description?: string | null;
  canonical?: string | null;
  /** Legacy ArticleHead callers can supply a distinct Open Graph URL. */
  og_url?: string | null;
  image?: string | null;
  site_name?: string | null;
  twitter_handle?: string | null;
  published_at?: string | null;
  author?: string | null;
  section?: string | null;
  index_in_search?: boolean;
  json_ld?: Record<string, unknown> | null;
  locale?: string | null;
  alternates?: Alternate[] | null;
  feed_url?: string | null;
  robots?: string | null;
}

/** Every server tag has a client twin with the same key. No fragments: Head does not flatten them. */
export function PublicHead({
  head,
  article = false,
}: {
  head: PublicHeadValues;
  article?: boolean;
}) {
  const {
    title,
    description,
    canonical,
    image,
    site_name,
    twitter_handle,
    published_at,
    author,
    section,
    json_ld,
    locale,
    feed_url,
  } = head;
  const ogUrl = head.og_url === undefined ? canonical : head.og_url;
  const alternates = head.alternates ?? [];
  const robots = article && head.index_in_search === false ? 'noindex,nofollow' : head.robots;
  return (
    <Head title={title}>
      {description && <meta head-key="description" name="description" content={description} />}
      {description && (
        <meta head-key="og:description" property="og:description" content={description} />
      )}
      <meta head-key="og:title" property="og:title" content={title} />
      <meta head-key="og:type" property="og:type" content={article ? 'article' : 'website'} />
      {ogUrl && <meta head-key="og:url" property="og:url" content={ogUrl} />}
      {site_name && <meta head-key="og:site_name" property="og:site_name" content={site_name} />}
      {article && published_at && (
        <meta
          head-key="article:published_time"
          property="article:published_time"
          content={published_at}
        />
      )}
      {article && author && (
        <meta head-key="article:author" property="article:author" content={author} />
      )}
      {article && section && (
        <meta head-key="article:section" property="article:section" content={section} />
      )}
      {article && image && <meta head-key="og:image" property="og:image" content={image} />}
      {article && image && <meta head-key="twitter:image" name="twitter:image" content={image} />}
      {article && (
        <meta
          head-key="twitter:card"
          name="twitter:card"
          content={image ? 'summary_large_image' : 'summary'}
        />
      )}
      {article && twitter_handle && (
        <meta head-key="twitter:site" name="twitter:site" content={twitter_handle} />
      )}
      {canonical && <link head-key="canonical" rel="canonical" href={canonical} />}
      {robots && <meta head-key="robots" name="robots" content={robots} />}
      {locale && <meta head-key="og:locale" property="og:locale" content={locale} />}
      {alternates
        .filter((a) => a.locale !== locale && a.locale !== 'x-default')
        .map((a) => (
          <meta
            key={a.locale}
            head-key={`og:locale:alternate-${a.locale}`}
            property="og:locale:alternate"
            content={a.locale}
          />
        ))}
      {alternates.map((a) => (
        <link
          key={a.locale}
          head-key={`hreflang-${a.locale}`}
          rel="alternate"
          hrefLang={a.locale}
          href={a.url}
        />
      ))}
      {feed_url && (
        <link
          head-key="feed"
          rel="alternate"
          type="application/rss+xml"
          title={title}
          href={feed_url}
        />
      )}
      {json_ld && (
        <script
          head-key="json-ld"
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: escaped JSON-LD, never executed
          dangerouslySetInnerHTML={{ __html: safeJsonLd(json_ld) }}
        />
      )}
    </Head>
  );
}
