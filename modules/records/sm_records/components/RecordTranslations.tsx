import { router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';
import { toast } from 'sonner';

import { createTranslation } from '../utils/api-history';
import { localeLabel } from '../utils/locale';
import type { RecordRead, TranslationRead } from '../utils/types';

interface Props {
  typeKey: string;
  record: RecordRead;
  /** Every content locale the module runs — only rendered by the caller
   *  when this has more than one entry. */
  locales: string[];
  /** The record's translation group, current record included — a view prop
   *  (`views.py::record_edit`'s `translations`) rather than a fetch this
   *  component makes itself: the editor already pays one query for it. */
  translations: TranslationRead[];
}

// See `FilterBar.tsx`'s header comment for why `t` is typed this loosely:
// `useT()`'s real signature either blows up TS with an "excessively deep"
// instantiation here or fails to unify when called.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

function siblingSubtitle(t: Translate, sibling: TranslationRead): string {
  const state =
    sibling.status === 'published'
      ? t('records.records.published', { defaultValue: 'Published' })
      : t('records.records.draft', { defaultValue: 'Draft' });
  if (!sibling.is_deleted) return `${sibling.display_title} · ${state}`;
  return `${sibling.display_title} · ${t('records.translations.trashed', { defaultValue: 'Trashed' })}`;
}

/**
 * The record's counterparts in the module's other content locales, modelled
 * on `news`' `ArticleTranslations` — a copy rather than a shared import,
 * since modules do not import each other's frontend code.
 *
 * A translation is a whole sibling record: its own uuid, its own slug in its
 * own locale, its own status. `translations` already includes the current
 * record (`contracts/i18n.py::TranslationRead`'s own header explains why: one
 * list rather than the record plus its siblings), so this panel never needs
 * a fetch of its own — the editor's page load already paid for it.
 */
export function RecordTranslations({ typeKey, record, locales, translations }: Props) {
  const { t } = useT();
  const [busyLocale, setBusyLocale] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const byLocale = new Map(translations.map((sibling) => [sibling.locale, sibling]));

  const handleAdd = async (target: string) => {
    setBusyLocale(target);
    setError(null);
    try {
      const created = await createTranslation(typeKey, record.uuid, { locale: target });
      // U9: this used to be entirely silent — a new record appeared, the URL
      // changed, and nothing said the action had actually done anything. The
      // toast names the language it created, since that's the one thing the
      // destination page's own header doesn't repeat back (it shows the
      // record's title, not "this is the German translation").
      toast.success(
        t('records.translations.created', {
          locale: localeLabel(target),
          defaultValue: '{locale} translation created',
        }),
      );
      // Straight into the new sibling: the next thing to do is translate it.
      router.visit(`/admin/records/${typeKey}/${created.uuid}`);
    } catch (err) {
      setBusyLocale(null);
      setError(err instanceof Error ? err.message : String(err));
      // A 409 here usually means the locale was taken between page load and
      // this click (another tab, another editor) — refetch so the row offers
      // "Open" for what now exists instead of a stale "Add" (UX-9).
      router.reload({ only: ['translations'] });
    }
  };

  return (
    <div data-testid="records-translations">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {t('records.translations.title', { defaultValue: 'Languages' })}
      </h2>
      <ul className="divide-y rounded-lg border bg-card text-sm">
        {locales.map((tag) => {
          const sibling = byLocale.get(tag);
          const isCurrent = tag === record.locale;
          return (
            <li
              key={tag}
              className="flex items-center justify-between gap-3 px-3 py-2"
              data-testid={`records-translation-${tag}`}
            >
              <span className="min-w-0">
                <span className="font-medium">{localeLabel(tag)}</span>
                {sibling && (
                  <span className="block truncate text-xs text-muted-foreground">
                    {siblingSubtitle(t, sibling)}
                  </span>
                )}
              </span>
              {isCurrent ? (
                <Badge variant="secondary" className="shrink-0">
                  {t('records.translations.editing', { defaultValue: 'Editing' })}
                </Badge>
              ) : sibling ? (
                <a
                  className="shrink-0 text-primary underline"
                  href={`/admin/records/${typeKey}/${sibling.uuid}`}
                  data-testid={`records-translation-open-${tag}`}
                >
                  {t('records.translations.open', { defaultValue: 'Open' })}
                </a>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busyLocale !== null}
                  onClick={() => void handleAdd(tag)}
                  data-testid={`records-translation-add-${tag}`}
                >
                  {busyLocale === tag
                    ? t('records.translations.creating', { defaultValue: 'Creating…' })
                    : t('records.translations.add', { defaultValue: 'Add translation' })}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      {error && (
        <p
          className="mt-2 text-sm text-destructive"
          role="alert"
          data-testid="records-translations-error"
        >
          {error}
        </p>
      )}
    </div>
  );
}
