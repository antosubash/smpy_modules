import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import type { ArticleDraft } from '../components/editor/ArticleInspector';
import {
  type ArticleRead,
  deleteArticle,
  listArticles,
  publishArticle,
  updateArticle,
} from '../utils/api';
import { SLUG_PATTERN } from '../utils/slugify';
import {
  type CategoryRead,
  listManagedCategories,
  listTags,
  setArticleTags,
} from '../utils/taxonomyApi';

/** Split a stored instant into the two controls the inspector shows.
 *
 * Read in UTC, because `published_at` is a display date stored at midnight UTC
 * — reading it in the viewer's own timezone shifts the date a day for everyone
 * west of UTC, which is the bug `formatArticleDate` already documents.
 */
function splitInstant(iso: string | null): { date: string; time: string } {
  if (!iso) return { date: '', time: '' };
  return { date: iso.slice(0, 10), time: iso.slice(11, 16) || '00:00' };
}

function toDraft(article: ArticleRead): ArticleDraft {
  const { date, time } = splitInstant(article.published_at);
  return {
    title: article.title,
    slug: article.slug,
    category: article.category,
    tags: article.tags ?? [],
    date,
    time,
    author: article.author ?? '',
    pinned: article.pinned ?? false,
    showInFeed: article.show_in_feed ?? true,
  };
}

/** Loads one article and saves the whole inspector in a single round trip.
 *
 * The draft is held here rather than per-control so a save is one request. Tags
 * are the exception: they live in their own table, so they go through their own
 * endpoint — but still on the same Save, so the screen has one action rather
 * than two that can disagree.
 */
export function useArticleEditor(articleId: number) {
  const [article, setArticle] = useState<ArticleRead | null>(null);
  const [draft, setDraft] = useState<ArticleDraft | null>(null);
  const [categories, setCategories] = useState<CategoryRead[]>([]);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        // No get-one endpoint: the listing is the one shape every article read
        // has, and adding a second would mean two places to keep in step.
        // `limit` is the API max so a mid-sized archive still finds the row.
        const response = await listArticles({ limit: 100, undated_first: true, signal });
        const found = response.items.find((a) => a.id === articleId) ?? null;
        if (signal?.aborted) return;
        if (found === null) {
          setError('That article no longer exists.');
          return;
        }
        setArticle(found);
        setDraft(toDraft(found));
        setDirty(false);
        setError(null);
      } catch (e) {
        if (signal?.aborted) return;
        setError((e as Error).message);
      }

      // Suggestions only — a failure here costs the selects their options and
      // nothing else, so it must not blank the screen.
      void Promise.all([listManagedCategories(signal), listTags(signal)])
        .then(([cats, tags]) => {
          if (signal?.aborted) return;
          setCategories(cats.items.filter((c) => !c.is_system));
          setTagSuggestions(tags.items.map((t) => t.name));
        })
        .catch(() => {});
    },
    [articleId],
  );

  const patch = useCallback((next: Partial<ArticleDraft>) => {
    setDraft((current) => (current ? { ...current, ...next } : current));
    setDirty(true);
    setSaved(false);
  }, []);

  const save = useCallback(async () => {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      // An empty date is a real value — it undates the article — so it is sent
      // as null rather than omitted.
      const publishedAt = draft.date ? `${draft.date}T${draft.time || '00:00'}:00Z` : null;
      const updated = await updateArticle(articleId, {
        // Sent every time rather than only when changed: the server compares
        // the incoming slug against the stored one and records a redirect only
        // for a real move, so an unchanged value costs nothing and diffing here
        // would be a second opinion about what counts as a rename.
        title: draft.title.trim(),
        slug: draft.slug,
        category: draft.category,
        published_at: publishedAt,
        pinned: draft.pinned,
        show_in_feed: draft.showInFeed,
        author: draft.author,
      });
      const tags = await setArticleTags(articleId, draft.tags);
      if (updated) setArticle({ ...updated, tags: tags ?? draft.tags });
      setDirty(false);
      setSaved(true);
      toast.success('Article saved');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [articleId, draft]);

  const publish = useCallback(async () => {
    if (!article) return;
    setBusy(true);
    setError(null);
    try {
      await publishArticle(article.id);
      await load();
      toast.success('Published');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [article, load]);

  const remove = useCallback(() => deleteArticle(articleId), [articleId]);

  /** Whether Save would be accepted.
   *
   * Checked here rather than left to the server because the two fields that can
   * fail are the two the DTO validates structurally: an empty title and a
   * malformed slug both come back as a 422 whose body names a Pydantic path,
   * which is not something this screen can turn into a sentence. A collision
   * still comes from the server — only it knows what is taken.
   */
  const valid = draft !== null && draft.title.trim().length > 0 && SLUG_PATTERN.test(draft.slug);

  return {
    article,
    draft,
    categories,
    tagSuggestions,
    busy,
    dirty,
    valid,
    saved,
    error,
    load,
    patch,
    save,
    publish,
    remove,
  };
}
