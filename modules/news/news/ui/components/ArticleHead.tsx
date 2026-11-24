import { Head } from '@inertiajs/react';
import { safeJsonLd } from '../utils/jsonLd';

/** Metadata shared by the stock article page and host replacements. */
export interface ArticleHeadProps {
  title: string;
  meta_description: string | null;
  og_image: string | null;
  canonical_url?: string | null;
  og_url?: string | null;
  index_in_search?: boolean;
  json_ld?: Record<string, unknown> | null;
  site_name?: string | null;
  twitter_handle?: string | null;
  category?: string;
  author?: string;
  published_at?: string | null;
}

export function ArticleHead({
  title,
  meta_description,
  og_image,
  canonical_url,
  og_url,
  index_in_search = true,
  json_ld,
  site_name,
  twitter_handle,
  category,
  author,
  published_at,
}: ArticleHeadProps) {
  const jsonLdScript = json_ld ? safeJsonLd(json_ld) : null;
  return (
    <Head title={title}>
      {meta_description && (
        <>
          <meta name="description" content={meta_description} />
          <meta property="og:description" content={meta_description} />
        </>
      )}
      <meta property="og:title" content={title} />
      {/* `article`, not `website` — the whole reason this module took its own
        address is that these documents are not generic pages, and the
        metadata should say so too. */}
      <meta property="og:type" content="article" />
      {og_url && <meta property="og:url" content={og_url} />}
      {site_name && <meta property="og:site_name" content={site_name} />}
      {published_at && <meta property="article:published_time" content={published_at} />}
      {author && <meta property="article:author" content={author} />}
      {category && <meta property="article:section" content={category} />}
      {og_image && (
        <>
          <meta property="og:image" content={og_image} />
          <meta name="twitter:image" content={og_image} />
        </>
      )}
      <meta name="twitter:card" content={og_image ? 'summary_large_image' : 'summary'} />
      {twitter_handle && <meta name="twitter:site" content={twitter_handle} />}
      {canonical_url && <link rel="canonical" href={canonical_url} />}
      {!index_in_search && <meta name="robots" content="noindex,nofollow" />}
      {jsonLdScript && (
        // Emitting author-composed JSON-LD is the feature. The content is
        // written by permission-holding editors and served under the app's CSP
        // (and NewsSettings.public_csp, when set).
        // biome-ignore lint/security/noDangerouslySetInnerHtml: author-composed JSON-LD is the feature
        <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript }} />
      )}
    </Head>
  );
}
