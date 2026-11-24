import { useCallback, useRef, useState } from 'react';
import { toast } from 'sonner';
import type { ArticleDraft } from '../components/editor/ArticleInspector';
import {
  type ArticleRead,
  getArticleDetail,
  publishArticle,
  trashArticle,
  updateArticle,
} from '../utils/api';
import { toDraft } from '../utils/articleDraft';
import { isHttpStatus } from '../utils/http';
import { keys, useT } from '../utils/i18n';
import { SLUG_PATTERN } from '../utils/slugify';
import {
  type CategoryRead,
  listManagedCategories,
  listTags,
  setArticleTags,
} from '../utils/taxonomyApi';
import { useArticleWriteQueue } from './useArticleWriteQueue';
import { useInFlight } from './useInFlight';

export type ArticleWrite = (
  action: (version: string | null) => Promise<ArticleRead | null>,
  restoreTitle?: boolean,
) => Promise<boolean>;

/** Server versions are UTC and retain Python's microsecond precision. */
function versionKey(iso: string): string {
  const [seconds, fraction = ''] = iso.replace(/(?:Z|\+00:00)$/, '').split('.');
  return `${seconds}.${fraction.padEnd(6, '0')}`;
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
  const articleRef = useRef<ArticleRead | null>(null);
  const [draft, setDraft] = useState<ArticleDraft | null>(null);
  const [categories, setCategories] = useState<CategoryRead[]>([]);
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([]);
  const { busy: saving, run: guardSave } = useInFlight();
  const { busy: publishing, run: guardPublish } = useInFlight();
  const busy = saving || publishing;
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const { mounted, runWrite, reset, error, setError, conflict } = useArticleWriteQueue();
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
        if (signal?.aborted || !mounted.current) return;
        articleRef.current = found;
        setArticle(found);
        setDraft(toDraft(found));
        setDirty(false);
        reset();
        setGone(false);
      } catch (e) {
        if (signal?.aborted || !mounted.current) return;
        setGone(isHttpStatus(e, 404));
        setError((e as Error).message);
      }

      // Suggestions only — a failure here costs the selects their options and
      // nothing else, so it must not blank the screen.
      void Promise.all([listManagedCategories(signal), listTags(signal)])
        .then(([cats, tags]) => {
          if (signal?.aborted || !mounted.current) return;
          setCategories(cats.items.filter((c) => !c.is_system));
          setTagSuggestions(tags.items.map((t) => t.name));
        })
        .catch(() => {});
    },
    [articleId, mounted, reset, setError],
  );

  /** Adopt a write response without discarding unsaved inspector fields.
   * Revision restore deliberately replaces the headline it restored. */
  const acceptWrite = useCallback(
    (updated: ArticleRead, restoreTitle = false) => {
      const current = articleRef.current;
      // Separate cards can finish out of order; an older response cannot undo a
      // later write or move the optimistic-concurrency stamp backwards.
      const older = Boolean(
        current?.updated_at &&
          updated.updated_at &&
          versionKey(updated.updated_at) < versionKey(current.updated_at),
      );
      // A later SEO/schedule write can already include this restore's title.
      // Honor that restore, but never replace a title saved after it.
      if (mounted.current && restoreTitle && (!older || current?.title === updated.title)) {
        setDraft((current) => (current ? { ...current, title: updated.title } : toDraft(updated)));
      }
      if (older) return;
      const next = { ...updated, tags: updated.tags ?? current?.tags ?? [] };
      articleRef.current = next;
      if (mounted.current) setArticle(next);
    },
    [mounted],
  );

  const patch = useCallback((next: Partial<ArticleDraft>) => {
    setDraft((current) => (current ? { ...current, ...next } : current));
    setDirty(true);
    setSaved(false);
  }, []);

  const writeArticle: ArticleWrite = useCallback(
    (action, restoreTitle = false) =>
      runWrite(async () => {
        const updated = await action(articleRef.current?.updated_at ?? null);
        if (updated) acceptWrite(updated, restoreTitle);
      }, true),
    [acceptWrite, runWrite],
  );

  const save = useCallback(
    () =>
      guardSave(() =>
        runWrite(async () => {
          if (!draft || !articleRef.current) return;
          // An empty date is a real value — it undates the article — so it is sent
          // as null rather than omitted.
          const publishedAt = draft.date ? `${draft.date}T${draft.time || '00:00'}:00Z` : null;
          // Metadata and tags form one queued write: no card can slip between
          // them and invalidate the stamp the metadata response just returned.
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
            expected_updated_at: articleRef.current.updated_at,
          });
          // Adopt immediately: even if tags fail, retry against the saved metadata.
          if (updated) acceptWrite(updated);
          const tags = await setArticleTags(articleId, draft.tags, articleRef.current.updated_at);
          acceptWrite({ ...articleRef.current, tags: tags ?? articleRef.current.tags });
          if (!mounted.current) return;
          setDirty(false);
          setSaved(true);
          toast.success(t(keys.news.editor.saved_toast));
        }),
      ),
    [acceptWrite, articleId, draft, guardSave, mounted, runWrite, t],
  );

  const publish = useCallback(
    () =>
      guardPublish(() =>
        runWrite(async () => {
          const updated = await publishArticle(articleId, articleRef.current?.updated_at);
          if (updated) acceptWrite(updated);
          if (mounted.current) toast.success(t(keys.news.editor.published_toast));
        }),
      ),
    [acceptWrite, articleId, guardPublish, mounted, runWrite, t],
  );

  const trash = useCallback(
    () =>
      runWrite(async () => {
        await trashArticle(articleId);
        if (mounted.current) toast.success(t(keys.news.trash.moved_toast));
      }),
    [articleId, mounted, runWrite, t],
  );

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
    acceptWrite,
    writeArticle,
    load,
    patch,
    save,
    publish,
    trash,
  };
}
