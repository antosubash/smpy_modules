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
  // Every element carries a `head-key` equal to the one the server wrote into
  // the document (`endpoints/public/_head.py`, `data-inertia`). That key is how
  // Inertia's head manager adopts the server's tag on hydration rather than
  // adding a second one beside it. Keep the two lists in step. No fragments:
  // `<Head>` does not flatten them, so each tag is its own conditional.
  return (
    <Head title={title}>
      {meta_description && (
        <meta head-key="description" name="description" content={meta_description} />
      )}
      {meta_description && (
        <meta head-key="og:description" property="og:description" content={meta_description} />
      )}
      <meta head-key="og:title" property="og:title" content={title} />
      {/* `article`, not `website` — the whole reason this module took its own
        address is that these documents are not generic pages, and the
        metadata should say so too. */}
      <meta head-key="og:type" property="og:type" content="article" />
      {og_url && <meta head-key="og:url" property="og:url" content={og_url} />}
      {site_name && <meta head-key="og:site_name" property="og:site_name" content={site_name} />}
      {published_at && (
        <meta
          head-key="article:published_time"
          property="article:published_time"
          content={published_at}
        />
      )}
      {author && <meta head-key="article:author" property="article:author" content={author} />}
      {category && (
        <meta head-key="article:section" property="article:section" content={category} />
      )}
      {og_image && <meta head-key="og:image" property="og:image" content={og_image} />}
      {og_image && <meta head-key="twitter:image" name="twitter:image" content={og_image} />}
      <meta
        head-key="twitter:card"
        name="twitter:card"
        content={og_image ? 'summary_large_image' : 'summary'}
      />
      {twitter_handle && (
        <meta head-key="twitter:site" name="twitter:site" content={twitter_handle} />
      )}
      {canonical_url && <link head-key="canonical" rel="canonical" href={canonical_url} />}
      {!index_in_search && <meta head-key="robots" name="robots" content="noindex,nofollow" />}
      {jsonLdScript && (
        // Emitting author-composed JSON-LD is the feature. The content is
        // written by permission-holding editors and served under the app's CSP
        // (and NewsSettings.public_csp, when set).
        <script
          head-key="json-ld"
          type="application/ld+json"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: author-composed JSON-LD is the feature
          dangerouslySetInnerHTML={{ __html: jsonLdScript }}
        />
      )}
    </Head>
  );
}
