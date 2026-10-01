import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import type { ArticleDraft } from '../components/editor/ArticleInspector';
import {
  type ArticleRead,
  deleteArticle,
  getArticleDetail,
  publishArticle,
  trashArticle,
  updateArticle,
} from '../utils/api';
import { isHttpStatus } from '../utils/http';
import { keys, useT } from '../utils/i18n';
import { SLUG_PATTERN } from '../utils/slugify';
import {
  type CategoryRead,
  listManagedCategories,
  listTags,
  setArticleTags,
} from '../utils/taxonomyApi';
import { useInFlight } from './useInFlight';

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
  const { t } = useT();
  const [article, setArticle] = useState<ArticleRead | null>(null);
  const [draft, setDraft] = useState<ArticleDraft | null>(null);
  const [categories, setCategories] = useState<CategoryRead[]>([]);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const { busy, run: guard } = useInFlight();
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Someone else changed the article since this copy was loaded. The edits on
   *  screen are kept; Save stays available only through Reload. */
  const [conflict, setConflict] = useState(false);
  /** The article was trashed or deleted elsewhere: nothing left to save to. */
  const [gone, setGone] = useState(false);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        // By id, not by searching a page of the listing: a page tops out at
        // the API's limit, past which an existing article read as deleted.
        // The detail shape *is* the listing row widened, tags included, and a
        // missing article answers 404 with its own message.
        const found = await getArticleDetail(articleId, signal);
        if (signal?.aborted) return;
        setArticle(found);
        setDraft(toDraft(found));
        setDirty(false);
        setError(null);
        setConflict(false);
        setGone(false);
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

  /** One place that turns a failed write into the right state: a stale write
   *  keeps the edits and offers Reload, a vanished article stops offering Save,
   *  anything else is just the banner. */
  const fail = useCallback(
    (e: unknown) => {
      if (isHttpStatus(e, 409)) setConflict(true);
      if (isHttpStatus(e, 404)) {
        setGone(true);
        setError(t(keys.news.errors.gone));
        return;
      }
      setError((e as Error).message);
    },
    [t],
  );

  const save = useCallback(
    () =>
      guard(async () => {
        if (!draft || !article) return;
        setError(null);
        // An empty date is a real value — it undates the article — so it is sent
        // as null rather than omitted.
        const publishedAt = draft.date ? `${draft.date}T${draft.time || '00:00'}:00Z` : null;
        // Run together — tags live in their own table, keyed only on the
        // article's id — but *settled* rather than raced: `Promise.all` rejects
        // on the first failure while the other call is still in flight and
        // unobserved, which is how a failed save used to be able to sit next to
        // a success message.
        const [meta, tagsResult] = await Promise.allSettled([
          updateArticle(articleId, {
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
            expected_updated_at: article.updated_at,
          }),
          setArticleTags(articleId, draft.tags),
        ]);
        // Every write response refreshes the copy, so the next save is made
        // against what the server now holds.
        if (meta.status === 'fulfilled' && meta.value) {
          const tags = tagsResult.status === 'fulfilled' ? tagsResult.value : null;
          setArticle({ ...meta.value, tags: tags ?? article.tags });
        }
        const failure = [meta, tagsResult].find((r) => r.status === 'rejected');
        if (failure) {
          fail((failure as PromiseRejectedResult).reason);
          return;
        }
        setDirty(false);
        setSaved(true);
        toast.success(t(keys.news.editor.saved_toast));
      }).catch(fail),
    [article, articleId, draft, fail, guard, t],
  );

  const publish = useCallback(
    () =>
      guard(async () => {
        if (!article) return;
        setError(null);
        await publishArticle(article.id);
        await load();
        toast.success(t(keys.news.editor.published_toast));
      }).catch(fail),
    [article, fail, guard, load, t],
  );

  // Hard delete. Requires `news.publish` on the server — see `deleteArticle`
  // — so the editor screen only offers it to a viewer who has it.
  const remove = useCallback(() => deleteArticle(articleId), [articleId]);

  // The recoverable door `news.edit` alone keeps open, for a viewer who
  // cannot hard-delete.
  const trash = useCallback(() => trashArticle(articleId), [articleId]);

  /** Whether Save would be accepted.
   *
   * Checked here rather than left to the server because the two fields that can
   * fail are the two the DTO validates structurally: an empty title and a
   * malformed slug both come back as a 422 whose body names a Pydantic path,
   * which is not something this screen can turn into a sentence. A collision
   * still comes from the server — only it knows what is taken.
   */
  const valid =
    !gone && draft !== null && draft.title.trim().length > 0 && SLUG_PATTERN.test(draft.slug);

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
    conflict,
    gone,
    /** Exposed so a sibling panel — the language switcher — reports through the
     *  same banner rather than growing an error surface of its own. */
    setError,
    load,
    patch,
    save,
    publish,
    remove,
    trash,
  };
}
