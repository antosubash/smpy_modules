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
import {
  NativeSelect,
  NativeSelectOptGroup,
} from '@simple-module-py/ui/components/ui/native-select';
import { useEffect, useState } from 'react';

import type { PageRead } from '../utils/api';
import { localeLabel, localePrefix } from '../utils/locale';
import { createPage, listPages, listTemplates } from '../utils/pagesApi';
import { slugify } from '../utils/slugify';

const TITLE_ID = 'new-page-title';
const SLUG_ID = 'new-page-slug';
const START_ID = 'new-page-start';
const PARENT_ID = 'new-page-parent';
const LOCALE_ID = 'new-page-locale';

const BLANK = '';

/** An empty Puck document — what "Blank" starts from. */
const EMPTY_DRAFT = { root: { props: { title: '', width: 'full' } }, content: [], zones: {} };

interface Props {
  publicPrefix?: string;
  /** Every language the site publishes in. A single entry hides the field —
   *  a select with one option is a question with one answer. */
  locales?: string[];
  defaultLocale?: string;
}

/** "New page" — title, URL, a starting point, and an optional breadcrumb parent.
 *
 * All changeable later, except the language. The dialog exists because some of
 * them are awkward to change *after* the fact: the URL leaves a stale link
 * behind, the starting point cannot be applied to a page that already has
 * content, and a page's language is fixed for its whole life — moving one
 * would strand its slug and orphan the redirect pointing at it, so the way to
 * a page in another language is a translation, not an edit.
 */
export function NewPageDialog({
  publicPrefix = '/p',
  locales = ['en'],
  defaultLocale = 'en',
}: Props) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  // Null until the author edits it: while it is null the slug tracks the title,
  // and the moment they type their own it stops being overwritten.
  const [slugOverride, setSlugOverride] = useState<string | null>(null);
  const [startFrom, setStartFrom] = useState(BLANK);
  const [parentId, setParentId] = useState('');
  const [locale, setLocale] = useState(defaultLocale);
  const [templates, setTemplates] = useState<PageRead[]>([]);
  const [pages, setPages] = useState<PageRead[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const slug = slugOverride ?? slugify(title);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    // The signal is threaded into the requests, not just checked afterwards:
    // without it, closing the dialog left both fetches running to completion.
    void Promise.all([listTemplates(controller.signal), listPages(controller.signal)])
      .then(([t, p]) => {
        if (controller.signal.aborted) return;
        setTemplates(t.items);
        setPages(p.items);
      })
      // Not worth a banner: without these the dialog still creates a blank
      // page, which is the common case anyway.
      .catch(() => {});
    return () => controller.abort();
  }, [open]);

  const reset = (next: boolean) => {
    if (pending) return;
    setOpen(next);
    if (!next) {
      setTitle('');
      setSlugOverride(null);
      setStartFrom(BLANK);
      setParentId('');
      setLocale(defaultLocale);
      setError(null);
    }
  };

  const create = async () => {
    setPending(true);
    setError(null);
    try {
      const page = await createPage({
        title: title.trim(),
        slug,
        locale,
        draft_data: EMPTY_DRAFT,
        ...(startFrom ? { copy_from_page_id: Number(startFrom) } : {}),
        ...(parentId ? { parent_id: Number(parentId) } : {}),
      });
      router.visit(`/pagebuilder/${page.id}/edit`);
    } catch (e) {
      setError((e as Error).message);
      setPending(false);
    }
  };

  const copyable = pages.filter((p) => !p.is_template);

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger asChild>
        <Button type="button">New page</Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim() && slug && !pending) void create();
          }}
        >
          <DialogHeader>
            <DialogTitle>New page</DialogTitle>
            <DialogDescription>
              A few fields, all changeable later except the language. Creating opens the editor.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor={TITLE_ID}>Title</Label>
              <Input
                id={TITLE_ID}
                value={title}
                autoFocus
                disabled={pending}
                placeholder="Field methods"
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>

            {locales.length > 1 && (
              <div className="grid gap-2">
                <Label htmlFor={LOCALE_ID}>Language</Label>
                <NativeSelect
                  id={LOCALE_ID}
                  value={locale}
                  disabled={pending}
                  onChange={(e) => {
                    setLocale(e.target.value);
                    // The parent select is scoped to the language, so a
                    // parent chosen under the old one is no longer on offer —
                    // leaving its id selected would submit a cross-language
                    // breadcrumb the list never showed.
                    setParentId('');
                  }}
                >
                  {locales.map((tag) => (
                    <option key={tag} value={tag}>
                      {localeLabel(tag)}
                    </option>
                  ))}
                </NativeSelect>
                <p className="text-xs text-muted-foreground">
                  Fixed once the page exists. To publish the same page in another language, add a
                  translation from the editor's Languages tab.
                </p>
              </div>
            )}

            <div className="grid gap-2">
              <Label htmlFor={SLUG_ID}>URL</Label>
              <div className="flex items-center gap-1">
                <span className="text-sm text-muted-foreground">
                  {localePrefix(locale, defaultLocale)}
                  {publicPrefix}/
                </span>
                <Input
                  id={SLUG_ID}
                  value={slug}
                  disabled={pending}
                  onChange={(e) => setSlugOverride(e.target.value)}
                />
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor={START_ID}>Start from</Label>
              <NativeSelect
                id={START_ID}
                value={startFrom}
                disabled={pending}
                onChange={(e) => setStartFrom(e.target.value)}
              >
                <option value={BLANK}>Blank</option>
                {templates.length > 0 && (
                  <NativeSelectOptGroup label="Templates">
                    {templates.map((t) => (
                      <option key={t.id} value={String(t.id)}>
                        {t.title}
                      </option>
                    ))}
                  </NativeSelectOptGroup>
                )}
                {copyable.length > 0 && (
                  <NativeSelectOptGroup label="Copy a page">
                    {copyable.map((p) => (
                      <option key={p.id} value={String(p.id)}>
                        {p.title}
                      </option>
                    ))}
                  </NativeSelectOptGroup>
                )}
              </NativeSelect>
              <p className="text-xs text-muted-foreground">
                Templates are ordinary pages flagged as templates, so the set grows without a
                developer.
              </p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor={PARENT_ID}>Parent</Label>
              <NativeSelect
                id={PARENT_ID}
                value={parentId}
                disabled={pending}
                onChange={(e) => setParentId(e.target.value)}
              >
                <option value="">None</option>
                {pages
                  .filter((p) => p.locale === locale)
                  .map((p) => (
                    <option key={p.id} value={String(p.id)}>
                      {p.title}
                    </option>
                  ))}
              </NativeSelect>
              <p className="text-xs text-muted-foreground">
                Optional. Affects the breadcrumb, not the URL. Only pages in the same language — a
                breadcrumb that crosses languages sends a reader out of theirs.
              </p>
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={() => reset(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !title.trim() || !slug}>
              {pending ? 'Creating…' : 'Create and open editor'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
