/** SEO metadata: title, description, social image, canonical, indexing, JSON-LD. */

import type { ReactNode } from 'react';

import { keys, useT } from '../../utils/i18n';
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
  const { t } = useT();
  return (
    <div className="grid grid-cols-1 gap-5 text-sm lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="flex items-baseline justify-between">
            <span className="font-medium">{t(keys.pagebuilder.seo.meta_title)}</span>
            <Counter value={metaTitle.length} limit={TITLE_LIMIT} />
          </span>
          <input
            type="text"
            value={metaTitle}
            onChange={(e) => onMetaTitleChange(e.target.value)}
            maxLength={200}
            placeholder={pageTitle || t(keys.pagebuilder.seo.meta_title_placeholder)}
            className="rounded border px-2 py-1"
          />
          <span className="text-xs text-muted-foreground">
            {t(keys.pagebuilder.seo.meta_title_help)}
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="flex items-baseline justify-between">
            <span className="font-medium">{t(keys.pagebuilder.seo.meta_description)}</span>
            <Counter value={metaDescription.length} limit={DESCRIPTION_LIMIT} />
          </span>
          <textarea
            value={metaDescription}
            onChange={(e) => onMetaDescriptionChange(e.target.value)}
            maxLength={500}
            rows={3}
            placeholder={t(keys.pagebuilder.seo.meta_description_placeholder)}
            className="rounded border px-2 py-1"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="font-medium">{t(keys.pagebuilder.seo.social_image)}</span>
          <input
            type="text"
            value={ogImage}
            onChange={(e) => onOgImageChange(e.target.value)}
            maxLength={500}
            placeholder={t(keys.pagebuilder.seo.social_image_placeholder)}
            className="rounded border px-2 py-1 font-mono"
          />
          {/* The middle of the sentence is a link, so it is three keys rather
              than one with a placeholder. */}
          <span className="text-xs text-muted-foreground">
            {t(keys.pagebuilder.seo.social_image_help_before)}{' '}
            <a href="/pagebuilder/media" className="text-primary hover:underline">
              {t(keys.pagebuilder.seo.social_image_help_link)}
            </a>
            {t(keys.pagebuilder.seo.social_image_help_after)}
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="font-medium">{t(keys.pagebuilder.seo.canonical)}</span>
          <input
            type="text"
            value={canonicalUrl}
            onChange={(e) => onCanonicalUrlChange(e.target.value)}
            maxLength={500}
            placeholder={t(keys.pagebuilder.seo.canonical_placeholder)}
            className="rounded border px-2 py-1 font-mono"
          />
          <span className="text-xs text-muted-foreground">
            {t(keys.pagebuilder.seo.canonical_help)}
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
            <span className="font-medium">{t(keys.pagebuilder.seo.allow_indexing)}</span>
            <span className="text-xs text-muted-foreground">
              {t(keys.pagebuilder.seo.allow_indexing_help_before)} <code>noindex,nofollow</code>{' '}
              {t(keys.pagebuilder.seo.allow_indexing_help_after)}
            </span>
          </span>
        </label>

        <label className="flex flex-col gap-1 md:col-span-2">
          <span className="font-medium">{t(keys.pagebuilder.seo.json_ld)}</span>
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
              {t(keys.pagebuilder.seo.json_ld_help_before)}{' '}
              <code>&lt;script type="application/ld+json"&gt;</code>
              {t(keys.pagebuilder.seo.json_ld_help_after)}
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
