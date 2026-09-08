/** Field state for the page editor, plus the derived write payload. */

import type { Data } from '@puckeditor/core';
import { useState } from 'react';

import { emptyData } from '../components/puckConfig';
import type { PageDetail } from '../utils/api';
import type { EditorSnapshot } from '../utils/editorSnapshot';
import { slugify } from '../utils/slugify';

export interface EditorForm {
  pageId: number | null;
  setPageId: (id: number | null) => void;
  /** Which language the page is written in.
   *
   * Read-only for the whole life of the page. A language is not a setting to
   * be corrected: moving a page between languages would strand its slug in the
   * old one, orphan the redirect that points at it, and either collide with or
   * duplicate the counterpart it is supposed to *be*. Wrong language means a
   * new page in the right one, which is what the Languages tab offers. */
  locale: string;
  title: string;
  setTitle: (v: string) => void;
  slug: string;
  setSlug: (v: string) => void;
  slugTouched: boolean;
  setSlugTouched: (v: boolean) => void;
  effectiveSlug: string;
  metaTitle: string;
  setMetaTitle: (v: string) => void;
  metaDescription: string;
  setMetaDescription: (v: string) => void;
  parentId: number | null;
  setParentId: (v: number | null) => void;
  showInHeaderNav: boolean;
  setShowInHeaderNav: (v: boolean) => void;
  showInFooter: boolean;
  setShowInFooter: (v: boolean) => void;
  /** The slug the page was loaded with — null for a page that has never been
   *  saved, which is how the settings panel knows whether a rename can strand
   *  a link that already exists. */
  savedSlug: string | null;
  ogImage: string;
  setOgImage: (v: string) => void;
  canonicalUrl: string;
  setCanonicalUrl: (v: string) => void;
  indexInSearch: boolean;
  setIndexInSearch: (v: boolean) => void;
  jsonLdText: string;
  jsonLdError: string | null;
  handleJsonLdChange: (v: string) => void;
  status: PageDetail['status'];
  setStatus: (v: PageDetail['status']) => void;
  publishAt: string | null;
  setPublishAt: (v: string | null) => void;
  unpublishAt: string | null;
  setUnpublishAt: (v: string | null) => void;
  data: Data;
  setData: (v: Data) => void;
  writePayload: () => Record<string, unknown>;
  snapshotPayload: EditorSnapshot;
  applyRestored: (restored: PageDetail) => EditorSnapshot;
}

export function useEditorForm(page: PageDetail | null, defaultLocale = 'en'): EditorForm {
  const [pageId, setPageId] = useState<number | null>(page?.id ?? null);
  const [title, setTitle] = useState(page?.title ?? 'Untitled page');
  const [slug, setSlug] = useState(page?.slug ?? '');
  const [slugTouched, setSlugTouched] = useState(Boolean(page?.slug));
  const [metaTitle, setMetaTitle] = useState(page?.meta_title ?? '');
  const [metaDescription, setMetaDescription] = useState(page?.meta_description ?? '');
  const [parentId, setParentId] = useState<number | null>(page?.parent_id ?? null);
  const [showInHeaderNav, setShowInHeaderNav] = useState<boolean>(
    page?.show_in_header_nav ?? false,
  );
  const [showInFooter, setShowInFooter] = useState<boolean>(page?.show_in_footer ?? false);
  const [ogImage, setOgImage] = useState(page?.og_image ?? '');
  const [canonicalUrl, setCanonicalUrl] = useState(page?.canonical_url ?? '');
  const [indexInSearch, setIndexInSearch] = useState<boolean>(page?.index_in_search ?? true);
  const [jsonLdText, setJsonLdText] = useState<string>(
    page?.json_ld ? JSON.stringify(page.json_ld, null, 2) : '',
  );
  const [jsonLdError, setJsonLdError] = useState<string | null>(null);
  const [status, setStatus] = useState<PageDetail['status']>(page?.status ?? 'draft');
  // ISO 8601 strings (with offset). The native ``datetime-local`` input
  // emits *naive* values like ``"2026-05-19T09:30"`` so we adapt at the
  // boundary in toLocalInput/fromLocalInput rather than carrying two
  // representations through component state.
  const [publishAt, setPublishAt] = useState<string | null>(page?.publish_at ?? null);
  const [unpublishAt, setUnpublishAt] = useState<string | null>(page?.unpublish_at ?? null);
  const [data, setData] = useState<Data>(
    (page?.draft_data as unknown as Data) || (emptyData as unknown as Data),
  );

  const effectiveSlug = slugTouched ? slug : slugify(title);

  const handleJsonLdChange = (value: string) => {
    setJsonLdText(value);
    const trimmed = value.trim();
    if (!trimmed) {
      setJsonLdError(null);
      return;
    }
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setJsonLdError('JSON-LD must be a JSON object.');
      } else {
        setJsonLdError(null);
      }
    } catch (err) {
      setJsonLdError(err instanceof Error ? err.message : 'Invalid JSON.');
    }
  };

  // ``json_ld`` is omitted from the payload when the editor textarea is
  // unparseable so a malformed draft doesn't silently overwrite a good
  // saved value. The ``jsonLdError`` state surfaces the parse error inline.
  const parseJsonLd = (): Record<string, unknown> | null | undefined => {
    const trimmed = jsonLdText.trim();
    if (!trimmed) return null;
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return undefined;
      }
      return parsed as Record<string, unknown>;
    } catch {
      return undefined;
    }
  };

  const writePayload = () => {
    const parsedLd = parseJsonLd();
    return {
      title,
      slug: effectiveSlug || slugify(title) || 'untitled',
      meta_title: metaTitle.trim() ? metaTitle.trim() : null,
      meta_description: metaDescription.trim() ? metaDescription.trim() : null,
      parent_id: parentId,
      show_in_header_nav: showInHeaderNav,
      show_in_footer: showInFooter,
      og_image: ogImage.trim() ? ogImage.trim() : null,
      canonical_url: canonicalUrl.trim() ? canonicalUrl.trim() : null,
      index_in_search: indexInSearch,
      // Only include json_ld in the payload when we have a valid parse;
      // ``undefined`` (parse error) is dropped so the server retains the
      // previously saved value.
      ...(parsedLd === undefined ? {} : { json_ld: parsedLd }),
    };
  };

  const snapshotPayload: EditorSnapshot = {
    title,
    slug: effectiveSlug,
    metaTitle,
    metaDescription,
    ogImage,
    canonicalUrl,
    indexInSearch,
    jsonLdText,
    parentId,
    showInHeaderNav,
    showInFooter,
    data,
  };

  /** Push a restored revision into the form; returns its snapshot. */
  const applyRestored = (restored: PageDetail): EditorSnapshot => {
    const restoredData = restored.draft_data as unknown as Data;
    const restoredCanonical = restored.canonical_url ?? '';
    const restoredIndex = restored.index_in_search ?? true;
    const restoredJsonLd = restored.json_ld ? JSON.stringify(restored.json_ld, null, 2) : '';
    setTitle(restored.title);
    setMetaDescription(restored.meta_description ?? '');
    setOgImage(restored.og_image ?? '');
    setCanonicalUrl(restoredCanonical);
    setIndexInSearch(restoredIndex);
    setJsonLdText(restoredJsonLd);
    setJsonLdError(null);
    setData(restoredData);
    return {
      title: restored.title,
      slug: restored.slug,
      metaDescription: restored.meta_description ?? '',
      ogImage: restored.og_image ?? '',
      canonicalUrl: restoredCanonical,
      indexInSearch: restoredIndex,
      jsonLdText: restoredJsonLd,
      // Carried from the form, not from `restored`: `restore_revision` writes
      // only title, meta_description, og_image and draft_data, so these four
      // are untouched by the restore and the form already holds the server's
      // values. Reading them off `restored` would work too — reading anything
      // else would make the page dirty the instant a revision is restored.
      metaTitle,
      parentId,
      showInHeaderNav,
      showInFooter,
      data: restoredData,
    };
  };

  return {
    pageId,
    setPageId,
    // A page that has never been saved is in the site's default language:
    // that is what `create` will give it, and showing anything else here
    // would be the editor guessing differently from the server.
    locale: page?.locale ?? defaultLocale,
    title,
    setTitle,
    slug,
    setSlug,
    slugTouched,
    setSlugTouched,
    effectiveSlug,
    savedSlug: page?.slug ?? null,
    metaTitle,
    setMetaTitle,
    metaDescription,
    setMetaDescription,
    parentId,
    setParentId,
    showInHeaderNav,
    setShowInHeaderNav,
    showInFooter,
    setShowInFooter,
    ogImage,
    setOgImage,
    canonicalUrl,
    setCanonicalUrl,
    indexInSearch,
    setIndexInSearch,
    jsonLdText,
    jsonLdError,
    handleJsonLdChange,
    status,
    setStatus,
    publishAt,
    setPublishAt,
    unpublishAt,
    setUnpublishAt,
    data,
    setData,
    writePayload,
    snapshotPayload,
    applyRestored,
  };
}
