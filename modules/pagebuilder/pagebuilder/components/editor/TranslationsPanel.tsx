import { router } from '@inertiajs/react';
import { useState } from 'react';

import type { PageStatus, PageTranslationRead } from '../../utils/api';
import { localeLabel, publicPath } from '../../utils/locale';
import { createTranslation } from '../../utils/pagesApi';

interface Props {
  pageId: number | null;
  /** The language the page open in the editor is written in. */
  locale: string;
  /** Every page in this one's group, itself included. */
  translations: PageTranslationRead[];
  /** Every language the site publishes in. */
  locales: string[];
  defaultLocale: string;
  /** Where pages serve publicly, for the address preview. */
  publicPrefix: string;
  onError: (message: string | null) => void;
}

const STATUS_LABEL: Record<PageStatus, string> = {
  draft: 'Draft',
  submitted_for_review: 'In review',
  published: 'Live',
};

/**
 * The page's counterparts in the site's other languages.
 *
 * A translation is an ordinary page — its own slug, its own draft, its own
 * approval workflow — so this panel deliberately does not try to be an editing
 * surface. It answers two questions and nothing else: which languages this
 * page exists in, and how to start the one it does not.
 *
 * Creating a translation navigates straight into it. The alternative, staying
 * here with a new row appearing in the list, leaves the author on a page they
 * have finished with and one click away from the one they asked for.
 */
export function TranslationsPanel({
  pageId,
  locale,
  translations,
  locales,
  defaultLocale,
  publicPrefix,
  onError,
}: Props) {
  const [busyLocale, setBusyLocale] = useState<string | null>(null);
  const bySlugLocale = new Map(translations.map((entry) => [entry.locale, entry]));

  // A page that has never been saved has no id to hang a group off, so there
  // is nothing to translate yet. Said plainly rather than by disabling a row
  // of buttons with no explanation.
  if (pageId === null) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="translations-unsaved">
        Save this page before adding a translation.
      </p>
    );
  }

  const handleAdd = async (target: string) => {
    setBusyLocale(target);
    onError(null);
    try {
      const created = await createTranslation(pageId, { locale: target });
      router.visit(`/pagebuilder/${created.id}/edit`);
    } catch (error) {
      setBusyLocale(null);
      onError(error instanceof Error ? error.message : 'Could not create the translation.');
    }
  };

  return (
    <div data-testid="translations-panel">
      <p className="mb-3 text-sm text-muted-foreground">
        This page is written in <strong>{localeLabel(locale)}</strong>. Each language has its own
        address, its own draft and its own approval — publishing one never publishes another.
      </p>
      <ul className="divide-y rounded-md border bg-background">
        {locales.map((entryLocale) => {
          const sibling = bySlugLocale.get(entryLocale);
          const isCurrent = entryLocale === locale;
          return (
            <li
              key={entryLocale}
              className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
              data-testid={`translation-row-${entryLocale}`}
            >
              <span className="min-w-0">
                <span className="font-medium">{localeLabel(entryLocale)}</span>
                <span className="ml-2 text-xs uppercase text-muted-foreground">{entryLocale}</span>
                {sibling && (
                  <span className="block truncate text-xs text-muted-foreground">
                    {publicPath(publicPrefix, sibling.slug, entryLocale, defaultLocale)} ·{' '}
                    {STATUS_LABEL[sibling.status]}
                  </span>
                )}
              </span>
              {isCurrent ? (
                <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-xs">Editing</span>
              ) : sibling ? (
                <a
                  className="shrink-0 text-primary underline"
                  href={`/pagebuilder/${sibling.id}/edit`}
                >
                  Open
                </a>
              ) : (
                <button
                  type="button"
                  className="shrink-0 rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
                  disabled={busyLocale !== null}
                  onClick={() => void handleAdd(entryLocale)}
                  data-testid={`add-translation-${entryLocale}`}
                >
                  {busyLocale === entryLocale ? 'Creating…' : 'Add translation'}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
