/** SEO metadata: title, description, social image, canonical, indexing, JSON-LD. */

import type { ReactNode } from 'react';

import { DESCRIPTION_LIMIT, SeoPreview, TITLE_LIMIT } from './SeoPreview';

interface Props {
  metaTitle: string;
  onMetaTitleChange: (value: string) => void;
  metaDescription: string;
  onMetaDescriptionChange: (value: string) => void;
  ogImage: string;
  onOgImageChange: (value: string) => void;
  canonicalUrl: string;
  onCanonicalUrlChange: (value: string) => void;
  indexInSearch: boolean;
  onIndexInSearchChange: (value: boolean) => void;
  jsonLdText: string;
  jsonLdError: string | null;
  onJsonLdChange: (value: string) => void;
  /** Fed to the preview so it shows what a reader would actually see. */
  pageTitle: string;
  slug: string;
  publicPrefix: string;
  host: string;
  /** Rendered inside the same grid, spanning both columns. */
  schedule: ReactNode;
}

/** A counter that turns amber past the limit rather than blocking input.
 *
 * The limits are soft: search engines truncate on pixel width, not characters,
 * so a hard cap would be its own kind of lie. What the writer needs is to see
 * the number, and to see the ellipsis land in the preview beside it.
 */
function Counter({ value, limit }: { value: number; limit: number }) {
  const over = value > limit;
  return (
    <span
      data-testid="seo-counter"
      className={`text-xs tabular-nums ${over ? 'font-medium text-amber-600' : 'text-muted-foreground'}`}
    >
      {value} / {limit}
    </span>
  );
}

export function SeoSettingsPanel({
  metaTitle,
  onMetaTitleChange,
  metaDescription,
  onMetaDescriptionChange,
  ogImage,
  onOgImageChange,
  canonicalUrl,
  onCanonicalUrlChange,
  indexInSearch,
  onIndexInSearchChange,
  jsonLdText,
  jsonLdError,
  onJsonLdChange,
  pageTitle,
  slug,
  publicPrefix,
  host,
  schedule,
}: Props) {
  return (
    <div className="grid grid-cols-1 gap-5 text-sm lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="flex items-baseline justify-between">
            <span className="font-medium">Meta title</span>
            <Counter value={metaTitle.length} limit={TITLE_LIMIT} />
          </span>
          <input
            type="text"
            value={metaTitle}
            onChange={(e) => onMetaTitleChange(e.target.value)}
            maxLength={200}
            placeholder={pageTitle || 'Falls back to the page title'}
            className="rounded border px-2 py-1"
          />
          <span className="text-xs text-muted-foreground">
            Leave blank to use the page title, which is right more often than not.
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="flex items-baseline justify-between">
            <span className="font-medium">Meta description</span>
            <Counter value={metaDescription.length} limit={DESCRIPTION_LIMIT} />
          </span>
          <textarea
            value={metaDescription}
            onChange={(e) => onMetaDescriptionChange(e.target.value)}
            maxLength={500}
            rows={3}
            placeholder="Shown in search results and link previews."
            className="rounded border px-2 py-1"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="font-medium">Social image</span>
          <input
            type="text"
            value={ogImage}
            onChange={(e) => onOgImageChange(e.target.value)}
            maxLength={500}
            placeholder="https://… or /media/pagebuilder/…"
            className="rounded border px-2 py-1 font-mono"
          />
          <span className="text-xs text-muted-foreground">
            1200×630. Paste a URL from the{' '}
            <a href="/pagebuilder/media" className="text-primary hover:underline">
              media library
            </a>
            , or leave blank to fall back to the first image on the page.
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="font-medium">Canonical URL</span>
          <input
            type="text"
            value={canonicalUrl}
            onChange={(e) => onCanonicalUrlChange(e.target.value)}
            maxLength={500}
            placeholder="Defaults to this page's own URL."
            className="rounded border px-2 py-1 font-mono"
          />
          <span className="text-xs text-muted-foreground">
            Override when this page duplicates content hosted elsewhere.
          </span>
        </label>

        <label className="mt-1 flex items-start gap-2 md:col-span-2">
          <input
            type="checkbox"
            checked={indexInSearch}
            onChange={(e) => onIndexInSearchChange(e.target.checked)}
            className="mt-1"
          />
          <span className="flex flex-col">
            <span className="font-medium">Allow search engines to index this page</span>
            <span className="text-xs text-muted-foreground">
              Uncheck to emit <code>noindex,nofollow</code> and exclude from the sitemap.
            </span>
          </span>
        </label>

        <label className="flex flex-col gap-1 md:col-span-2">
          <span className="font-medium">JSON-LD structured data</span>
          <textarea
            value={jsonLdText}
            onChange={(e) => onJsonLdChange(e.target.value)}
            rows={5}
            placeholder='{"@context":"https://schema.org","@type":"Article",…}'
            className="rounded border px-2 py-1 font-mono text-xs"
          />
          {jsonLdError ? (
            <span className="text-xs text-destructive" data-testid="json-ld-error">
              {jsonLdError}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">
              Embedded inside <code>&lt;script type="application/ld+json"&gt;</code>. Leave blank to
              omit.
            </span>
          )}
        </label>

        <div className="md:col-span-2">{schedule}</div>
      </div>

      <SeoPreview
        host={host}
        slug={slug}
        publicPrefix={publicPrefix}
        metaTitle={metaTitle}
        pageTitle={pageTitle}
        metaDescription={metaDescription}
        socialImage={ogImage}
      />
    </div>
  );
}
