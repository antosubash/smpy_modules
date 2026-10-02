import { Head } from '@inertiajs/react';
import { type Data, Render } from '@puckeditor/core';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { useEffect } from 'react';
import { Byline } from '../components/Byline';
import { articlePuckConfig } from '../components/body/articlePuckConfig';
import { articleOutline } from '../components/body/blocks/outline';
import { type Alternate, LanguageSwitch } from '../components/LanguageSwitch';
import { type ArticlePreviewState, PreviewBanner } from '../components/PreviewBanner';
import { useDocumentLang } from '../hooks/useDocumentLang';
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
  /** The byline's archive, or null when the byline has no address — a name in
   *  a script that leaves nothing to slugify. Null renders the byline as plain
   *  text rather than as a link somewhere that cannot name this author. */
  author_url?: string | null;
  published_at?: string | null;
  /** The article's language, and the same article in the others (with an
   *  `x-default` entry for crawlers, which the switch skips). */
  locale?: string;
  alternates?: Alternate[];
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

/**
 * Re-apply a `#section` the reader arrived with.
 *
 * The browser resolves the fragment while the document is still the Inertia
 * blob — the body is a block tree React draws afterwards, so the heading the
 * link names does not exist yet when the fragment is first looked up. Clicking
 * an entry in `Contents` is unaffected either way; this is only for a link
 * that arrived from somewhere else, which is the half a section anchor exists
 * for.
 *
 * Once, on mount. A later navigation is Inertia's to scroll.
 *
 * **This is untested, and not for want of trying.** `tests/e2e/`
 * `article-contents.spec.ts` is named after this behaviour but asserts the
 * *outcome* — that arriving at `/news/{slug}#section` lands on that section —
 * and it passes with this hook deleted. Chromium does not need it: Blink keeps
 * a pending fragment scroll and re-applies it when the late-rendered element
 * appears, which held even with the page module delayed 2.5s past `load`. The
 * premise above ("the reader lands at the top of the article") is therefore
 * false in the only engine the suite runs.
 *
 * It stays because untested in WebKit and Firefox is not the same as
 * unnecessary — neither is exercised here, and neither is promised to hold a
 * pending scroll the way Blink does. Do not read the spec's name as coverage
 * for this function; nothing in the suite fails if it goes.
 */
function useAnchorOnArrival() {
  useEffect(() => {
    const anchor = window.location.hash.slice(1);
    if (!anchor) return;
    document.getElementById(anchor)?.scrollIntoView();
  }, []);
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
  author_url,
  published_at,
  locale,
  alternates,
  preview,
}: Props) {
  useAnchorOnArrival();
  useDocumentLang(locale);
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
          {/* The byline links to everything else under it. A reader who
              finishes a piece and wants more of the same writer had nowhere to
              go before — the category and the tags were both links and the
              person who wrote it was not. Its own component because the
              link-or-plain-text rule is the part that must not slip. */}
          <Byline author={author} dated={dated} url={author_url} />
          <LanguageSwitch alternates={alternates} current={locale} />
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
        {/* `metadata` is how a block learns what it is inside — the seam for
            any block that needs the article rather than its own props.
            `Related` reads the slug, because a "read next" list that includes
            the article you are reading is visibly broken; `Contents` and
            `Heading` read the outline, because Puck hands a `render` function
            no way to see its siblings and a contents list is nothing but a
            statement about them. The canvas builds the same outline the same
            way, so the anchors match on both screens. */}
        {/* The raw config, labels and all: `<Render>` draws blocks, never the
            panel that names them, so the catalogue keys the config carries
            never reach a reader. The canvas localizes it — see `ArticleBody`. */}
        <Render
          config={articlePuckConfig}
          data={data as unknown as Data}
          metadata={{ currentSlug: slug, outline: articleOutline(data) }}
        />
      </article>
    </div>
  );
}
