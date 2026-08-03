/** SEO metadata drawer: description, OG image, canonical, indexing, JSON-LD. */

import type { ReactNode } from 'react';

interface Props {
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
  /** Rendered inside the same grid, spanning both columns. */
  schedule: ReactNode;
}

export function SeoSettingsPanel({
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
  schedule,
}: Props) {
  return (
    <div className="border-b bg-gray-50 px-4 py-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
      <label className="flex flex-col gap-1">
        <span className="font-medium text-gray-700">Meta description</span>
        <textarea
          value={metaDescription}
          onChange={(e) => onMetaDescriptionChange(e.target.value)}
          maxLength={500}
          rows={2}
          placeholder="Shown in search results and link previews."
          className="border rounded px-2 py-1"
        />
        <span className="text-xs text-gray-500">{metaDescription.length}/500</span>
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-medium text-gray-700">Open Graph image URL</span>
        <input
          type="text"
          value={ogImage}
          onChange={(e) => onOgImageChange(e.target.value)}
          maxLength={500}
          placeholder="https://… or /media/pagebuilder/…"
          className="border rounded px-2 py-1 font-mono"
        />
        <span className="text-xs text-gray-500">
          Paste a URL from the{' '}
          <a href="/pagebuilder/media" className="text-blue-600 hover:underline">
            media library
          </a>
          .
        </span>
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-medium text-gray-700">Canonical URL</span>
        <input
          type="text"
          value={canonicalUrl}
          onChange={(e) => onCanonicalUrlChange(e.target.value)}
          maxLength={500}
          placeholder="Defaults to this page's own URL."
          className="border rounded px-2 py-1 font-mono"
        />
        <span className="text-xs text-gray-500">
          Override when this page is a duplicate of content hosted elsewhere.
        </span>
      </label>
      <label className="flex items-start gap-2 mt-1">
        <input
          type="checkbox"
          checked={indexInSearch}
          onChange={(e) => onIndexInSearchChange(e.target.checked)}
          className="mt-1"
        />
        <span className="flex flex-col">
          <span className="font-medium text-gray-700">Allow search engines to index this page</span>
          <span className="text-xs text-gray-500">
            Uncheck to emit <code>noindex,nofollow</code> and exclude from sitemap.
          </span>
        </span>
      </label>
      <label className="flex flex-col gap-1 md:col-span-2">
        <span className="font-medium text-gray-700">JSON-LD structured data</span>
        <textarea
          value={jsonLdText}
          onChange={(e) => onJsonLdChange(e.target.value)}
          rows={6}
          placeholder='{"@context":"https://schema.org","@type":"Article",…}'
          className="border rounded px-2 py-1 font-mono text-xs"
        />
        {jsonLdError ? (
          <span className="text-xs text-red-600" data-testid="json-ld-error">
            {jsonLdError}
          </span>
        ) : (
          <span className="text-xs text-gray-500">
            Embedded inside <code>&lt;script type="application/ld+json"&gt;</code>. Leave blank to
            omit.
          </span>
        )}
      </label>

      {schedule}
    </div>
  );
}
