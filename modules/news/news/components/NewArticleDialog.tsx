import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useEffect, useState } from 'react';

import { createArticle } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { localeLabel } from '../utils/locale';
import { SLUG_PATTERN, slugify } from '../utils/slugify';
import { type CategoryRead, listManagedCategories } from '../utils/taxonomyApi';

const HEADLINE_ID = 'news-new-article-headline';
const SLUG_ID = 'news-new-article-slug';
const CATEGORY_ID = 'news-new-article-category';
const DATE_ID = 'news-new-article-date';
const LOCALE_ID = 'news-new-article-locale';

/** The server's column bounds — `title` and `slug` on the create DTO. */
const MAX_TITLE_LEN = 300;
const MAX_SLUG_LEN = 200;

/** Today in the UTC calendar, which is the calendar `published_at` is stored in. */
function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

interface Props {
  /** Every language the site publishes in. One or none hides the field. */
  locales?: string[];
  defaultLocale?: string;
}

/** "New article" — headline, URL, category, date. All changeable later, except
 * the language.
 *
 * The date defaults to today rather than to empty: an article with no date is
 * work in progress, and defaulting to that would make every new article land in
 * the undated pile whether or not its author meant it to.
 *
 * The language is fixed once the article exists: a slug is unique per
 * `(locale, slug)`, so moving one would strand its slug in the old language and
 * orphan the redirect pointing at it. The way to the same story in another
 * language is a translation, offered from the editor.
 */
export function NewArticleDialog({ locales = [], defaultLocale = 'en' }: Props) {
  const { t } = useT();
  const copy = keys.news.new_article;
  const [open, setOpen] = useState(false);
  const [headline, setHeadline] = useState('');
  // Null until edited: while null the slug tracks the headline, and the moment
  // an author types their own it stops being overwritten under them.
  const [slugOverride, setSlugOverride] = useState<string | null>(null);
  const [category, setCategory] = useState('');
  const [date, setDate] = useState(todayUtc);
  const [locale, setLocale] = useState(defaultLocale);
  const [categories, setCategories] = useState<CategoryRead[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const slug = slugOverride ?? slugify(headline);
  // The same rule, and the same sentence, as the editor's URL field. An empty
  // address is not invalid: the server derives one (falling back to "item" for
  // a headline with nothing an address can use), so it only gets a hint.
  const slugInvalid = slug !== '' && !SLUG_PATTERN.test(slug);
  const slugEmpty = slug === '' && headline.trim() !== '';

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    // The *managed* list, not the public one: the public listing counts only
    // published articles, so a category that exists but has not been used yet
    // would never be offered — which is exactly when you want to pick it.
    void listManagedCategories(controller.signal)
      .then((response) => setCategories(response.items.filter((c) => !c.is_system)))
      // Not worth a banner: without it the select offers Uncategorised only,
      // and the category is editable from the list afterwards anyway.
      .catch(() => {});
    return () => controller.abort();
  }, [open]);

  const reset = (next: boolean) => {
    if (pending) return;
    setOpen(next);
    if (!next) {
      setHeadline('');
      setSlugOverride(null);
      setCategory('');
      setDate(todayUtc());
      setLocale(defaultLocale);
      setError(null);
    }
  };

  const create = async () => {
    setPending(true);
    setError(null);
    try {
      // One request, one insert. This used to be two calls from here —
      // creating the page through pagebuilder's API and then attaching — which
      // needed both a borrowed CSRF cookie and a `created` state to remember
      // the page a failed attempt had already committed, so a retry could adopt
      // it instead of stranding another empty one. Neither is reachable any
      // more: a failure now leaves nothing behind to adopt.
      const article = await createArticle({
        title: headline.trim(),
        // Only when the author actually typed one. While `slugOverride` is
        // null the field is a *preview* of what the headline derives, and
        // sending it would turn a second article of the same headline into a
        // "Slug already in use" dead end — the server can only take the next
        // free variant for a slug nobody asked for by name.
        slug: slugOverride || undefined,
        locale,
        category,
        published_at: date ? `${date}T00:00:00Z` : null,
      });
      // `write` types its result as `T | null` because a 204 carries no body.
      // This route answers 201 with the article, so the null branch is
      // unreachable — but reading `edit_url` off null would throw past the
      // catch below and leave the dialog stuck on "Creating…" with both
      // buttons disabled, which is the one outcome worth three lines to avoid.
      if (!article) throw new Error(t(copy.empty_response));
      // `edit_url` is the body canvas: creating an article and writing it are
      // one motion. It used to be a pagebuilder editor URL, which is why this
      // is served by the API rather than assembled here.
      router.visit(article.edit_url, {
        // A visit that lands unmounts this component, so this only fires when
        // one does not. Without it a failed navigation leaves the dialog on
        // "Creating…" with both buttons disabled, permanently.
        onFinish: () => setPending(false),
      });
    } catch (e) {
      setError((e as Error).message);
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger asChild>
        <Button type="button">{t(copy.trigger)}</Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (headline.trim() && !slugInvalid && !pending) void create();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t(copy.title)}</DialogTitle>
            <DialogDescription>{t(copy.description)}</DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor={HEADLINE_ID}>{t(copy.headline_label)}</Label>
              <Input
                id={HEADLINE_ID}
                value={headline}
                autoFocus
                maxLength={MAX_TITLE_LEN}
                disabled={pending}
                placeholder={t(copy.headline_placeholder)}
                onChange={(e) => setHeadline(e.target.value)}
              />
            </div>

            {locales.length > 1 && (
              <div className="grid gap-2">
                <Label htmlFor={LOCALE_ID}>{t(copy.language_label)}</Label>
                <NativeSelect
                  id={LOCALE_ID}
                  value={locale}
                  disabled={pending}
                  onChange={(e) => setLocale(e.target.value)}
                >
                  {locales.map((tag) => (
                    <option key={tag} value={tag}>
                      {localeLabel(tag)}
                    </option>
                  ))}
                </NativeSelect>
                <p className="text-xs text-muted-foreground">{t(copy.language_help)}</p>
              </div>
            )}

            <div className="grid gap-2">
              <Label htmlFor={SLUG_ID}>{t(copy.url_label)}</Label>
              <div className="flex items-center gap-1">
                <span className="text-sm text-muted-foreground">
                  {locale === defaultLocale ? '' : `/${locale}`}/news/
                </span>
                <Input
                  id={SLUG_ID}
                  value={slug}
                  maxLength={MAX_SLUG_LEN}
                  disabled={pending}
                  aria-invalid={slugInvalid || undefined}
                  onChange={(e) => setSlugOverride(e.target.value)}
                />
              </div>
              {slugInvalid && (
                <p className="text-xs text-destructive">{t(keys.news.inspector.slug_invalid)}</p>
              )}
              {slugEmpty && <p className="text-xs text-muted-foreground">{t(copy.url_needed)}</p>}
            </div>

            <div className="grid gap-2">
              <Label htmlFor={CATEGORY_ID}>{t(copy.category_label)}</Label>
              <NativeSelect
                id={CATEGORY_ID}
                value={category}
                disabled={pending}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">{t(copy.category_none)}</option>
                {categories.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            </div>

            <div className="grid gap-2">
              <Label htmlFor={DATE_ID}>{t(copy.date_label)}</Label>
              <Input
                id={DATE_ID}
                type="date"
                value={date}
                disabled={pending}
                onChange={(e) => setDate(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">{t(copy.date_help)}</p>
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={() => reset(false)}>
              {t(copy.cancel)}
            </Button>
            <Button type="submit" disabled={pending || !headline.trim() || slugInvalid}>
              {pending ? t(copy.creating) : t(copy.create)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
