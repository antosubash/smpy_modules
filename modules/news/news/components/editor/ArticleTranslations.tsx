import { router } from '@inertiajs/react';
import { useEffect, useState } from 'react';

import { type ArticleRead, listArticles, translateArticle } from '../../utils/api';
import { localeLabel } from '../../utils/locale';

interface Props {
  article: ArticleRead;
  /** Every language the site publishes in. */
  locales: string[];
  onError: (message: string | null) => void;
}

/**
 * The article's counterparts in the site's other languages.
 *
 * A translation is an ordinary article on an ordinary page — its own slug, its
 * own body, its own publish state — so this panel only answers which languages
 * the story exists in and offers to start the ones it does not.
 *
 * Category, byline and date are not asked for again when adding one. They are
 * facts about the story rather than about the language it is told in, so the
 * server copies them across; a form that asked would invite them to drift.
 */
export function ArticleTranslations({ article, locales, onError }: Props) {
  const [siblings, setSiblings] = useState<ArticleRead[] | null>(null);
  const [busyLocale, setBusyLocale] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    // The ordinary listing, filtered to the group: it already applies the
    // visibility rule, so a reader without `news.edit` sees the published
    // translations and nothing else, exactly as they would anywhere else.
    void listArticles({
      translation_group: article.translation_group,
      limit: locales.length,
      signal: controller.signal,
    })
      .then((response) => setSiblings(response.items))
      // The panel is the only thing that degrades; the rest of the inspector
      // still saves.
      .catch(() => setSiblings([]));
    return () => controller.abort();
  }, [article.translation_group, locales.length]);

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
      if (created === null) throw new Error('The translation was created but not returned.');
      router.visit(created.edit_url);
    } catch (error) {
      setBusyLocale(null);
      onError(error instanceof Error ? error.message : 'Could not create the translation.');
    }
  };

  return (
    <div data-testid="article-translations">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide">Languages</h2>
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
                    {sibling.url} · {sibling.page_status === 'published' ? 'Live' : 'Draft'}
                  </span>
                )}
              </span>
              {isCurrent ? (
                <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs">Editing</span>
              ) : sibling ? (
                <a className="shrink-0 text-primary underline" href={sibling.edit_url}>
                  Open
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
                  {busyLocale === tag ? 'Creating…' : 'Add translation'}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
