import { router } from '@inertiajs/react';
import { useEffect, useState } from 'react';

import {
  type ArticleRead,
  type ArticleStatus,
  listArticles,
  translateArticle,
} from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { localeLabel } from '../../utils/locale';

/** Three words for three states. A submission is not a draft the author is
 *  still holding and it is not live either, and "Draft" for both is how a
 *  reviewer ends up chasing a translation that is already waiting on them. */
const STATUS_WORD: Record<ArticleStatus, string> = {
  draft: keys.news.translations.status_draft,
  submitted_for_review: keys.news.translations.status_pending,
  published: keys.news.translations.status_published,
};

interface Props {
  article: ArticleRead;
  /** Every language the site publishes in. */
  locales: string[];
  onError: (message: string | null) => void;
}

/**
 * The article's counterparts in the site's other languages.
 *
 * A translation is a sibling article — its own slug, its own body, its own
 * workflow state — sharing a `translation_group` with this one, so this panel
 * only answers which languages the story exists in and offers to start the ones
 * it does not.
 *
 * Category, byline and date are not asked for again when adding one. They are
 * facts about the story rather than about the language it is told in, so the
 * server copies them across; a form that asked would invite them to drift.
 */
export function ArticleTranslations({ article, locales, onError }: Props) {
  const { t } = useT();
  const copy = keys.news.translations;
  const [siblings, setSiblings] = useState<ArticleRead[] | null>(null);
  const [busyLocale, setBusyLocale] = useState<string | null>(null);
  const group = article.translation_group;

  useEffect(() => {
    // Emptiness, not presence. An article with no group is a group of one, and
    // the degenerate value is `""` — which `listArticles` treats as "no filter
    // given" and answers with every article on the site. Without this guard
    // they would all render here as counterparts of this story. Invisible
    // against a single-article fixture, wrong the moment a second unrelated
    // article exists.
    if (!group) {
      setSiblings([]);
      return;
    }
    const controller = new AbortController();
    // The ordinary listing, filtered to the group: it already applies the
    // visibility rule, so a reader without `news.edit` sees the published
    // translations and nothing else, exactly as they would anywhere else.
    void listArticles({
      translation_group: group,
      limit: locales.length,
      signal: controller.signal,
    })
      .then((response) => setSiblings(response.items))
      // The panel is the only thing that degrades; the rest of the inspector
      // still saves.
      .catch(() => setSiblings([]));
    return () => controller.abort();
  }, [group, locales.length]);

  const byLocale = new Map((siblings ?? []).map((entry) => [entry.locale, entry]));

  const handleAdd = async (target: string) => {
    setBusyLocale(target);
    onError(null);
    try {
      const created = await translateArticle(article.id, { locale: target });
      // Straight into the new one: the author's next move is to translate it,
      // and leaving them on the article they have finished with would be a
      // row appearing in a list they are about to navigate away from.
      //
      // `write` types a 204 as null; this route answers 201 with a body, so
      // null here means the shape changed rather than "nothing was created" —
      // say so instead of navigating to `undefined`.
      if (created === null) throw new Error(t(copy.empty_response));
      router.visit(created.edit_url);
    } catch (error) {
      setBusyLocale(null);
      onError(error instanceof Error ? error.message : t(copy.failed));
    }
  };

  return (
    <div data-testid="article-translations">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide">{t(copy.heading)}</h2>
      <ul className="divide-y rounded-lg border bg-card text-sm">
        {locales.map((tag) => {
          const sibling = byLocale.get(tag);
          const isCurrent = tag === article.locale;
          return (
            <li
              key={tag}
              className="flex items-center justify-between gap-3 px-3 py-2"
              data-testid={`article-translation-${tag}`}
            >
              <span className="min-w-0">
                <span className="font-medium">{localeLabel(tag)}</span>
                {sibling && (
                  <span className="block truncate text-xs text-muted-foreground">
                    {sibling.url} · {t(STATUS_WORD[sibling.status])}
                  </span>
                )}
              </span>
              {isCurrent ? (
                <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs">
                  {t(copy.editing)}
                </span>
              ) : sibling ? (
                <a className="shrink-0 text-primary underline" href={sibling.edit_url}>
                  {t(copy.open)}
                </a>
              ) : (
                <button
                  type="button"
                  className="shrink-0 rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
                  // Disabled until the siblings are known: offering "Add" for a
                  // language that already has one turns a click into a 409.
                  disabled={siblings === null || busyLocale !== null}
                  onClick={() => void handleAdd(tag)}
                  data-testid={`add-article-translation-${tag}`}
                >
                  {busyLocale === tag ? t(copy.creating) : t(copy.add)}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
