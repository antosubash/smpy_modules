import { Head } from '@inertiajs/react';
import { type Data, Render } from '@puckeditor/core';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';

import { articlePuckConfig } from '../components/body/articlePuckConfig';
import { type ArticlePreviewState, PreviewBanner } from '../components/PreviewBanner';
import { formatArticleDate } from '../utils/api';

/** What a reader gets at `{public_route_prefix}/{slug}`.
 *
 * News owned this address before it owned this screen: the route resolved a
 * slug and handed off to pagebuilder's public page viewer, because the body was
 * one of its pages and a second viewer would have meant a second copy of the
 * ETag, cache, CSP, canonical and redirect handling.
 *
 * The body is a news column now, so this is the only thing that can render it.
 * The headers that hand-off used to carry are on the server side of this route
 * — see `news/endpoints/public/`; what is here is the document and its
 * metadata.
 */

interface Props {
  title: string;
  /** Which article this is. Handed to the block document as Puck metadata so a
   *  block can know what it is inside — see the `<Render>` call below. */
  slug?: string;
  data: Record<string, unknown>;
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
  /** Present only on the authenticated preview at
   *  `{VIEW_PREFIX}/articles/{id}/preview`, which renders this same screen over
   *  `draft_data` so a reviewer approving an article has actually read it.
   *
   *  One screen rather than two on purpose: a preview that rendered
   *  differently from the real thing would be worthless, and a second viewer
   *  would be a second copy of the head, the canonical and the `hreflang`
   *  handling. The banner is the only thing that differs, and the server
   *  omits this prop entirely on the public route. */
  preview?: ArticlePreviewState | null;
}

// Inline JSON-LD as a string requires the document to be safe to embed inside
// ``<script>...</script>``. ``JSON.stringify`` does not escape the literal
// sequence ``</`` (or HTML comment openers), so a value like
// ``"</script><script>alert(1)</script>"`` would break out. The replace runs
// over keys and string values alike; ``<\/`` parses identically to ``</`` in
// JSON, so the document round-trips through any consumer.
function safeJsonLd(doc: Record<string, unknown>): string {
  return JSON.stringify(doc)
    .replace(/<\/(script)/gi, '<\\/$1')
    .replace(/<!--/g, '<\\!--');
}

export default function PublicArticle({
  title,
  slug,
  data,
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
  preview,
}: Props) {
  const jsonLdScript = json_ld ? safeJsonLd(json_ld) : null;
  const dated = formatArticleDate(published_at ?? null);

  return (
    <div>
      {/* A public page has no admin layout, so without this the configured
          brand colour and favicon would stop at the sign-in wall. */}
      <BrandingHead />
      {preview && <PreviewBanner preview={preview} />}
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
          // written by permission-holding editors and served under the CSP in
          // NewsSettings.public_csp.
          // biome-ignore lint/security/noDangerouslySetInnerHtml: author-composed JSON-LD is the feature
          <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdScript }} />
        )}
      </Head>

      <article>
        <header className="mx-auto max-w-2xl px-4 pt-12">
          {category && (
            <p className="mb-2 text-sm font-medium uppercase tracking-wide text-primary">
              {category}
            </p>
          )}
          {/* The article's title is the document's only `<h1>` — which is why
              the body's Heading block starts at level 2. */}
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
          {(author || dated) && (
            <p className="mt-3 text-sm text-muted-foreground">
              {[author, dated].filter(Boolean).join(' · ')}
            </p>
          )}
          {og_image && (
            <img
              src={og_image}
              alt=""
              className="mt-8 w-full rounded-lg"
              // The cover is the first thing on screen, so it is the LCP
              // element — lazy-loading it would delay exactly the paint the
              // reader is waiting on.
              fetchPriority="high"
            />
          )}
        </header>
        {/* `metadata` is how a block learns what it is inside. Only `Related`
            wants it today — a "read next" list that includes the article you
            are reading is visibly broken — but it is the seam for any block
            that needs the article rather than its own props. */}
        <Render
          config={articlePuckConfig}
          data={data as unknown as Data}
          metadata={{ currentSlug: slug }}
        />
      </article>
    </div>
  );
}
