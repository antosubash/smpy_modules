import { router } from '@inertiajs/react';
import { slugify } from '@simple-module-py/pagebuilder/pagebuilder/utils/slugify';
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

import { articleEditUrl, attachArticle, createArticlePage } from '../utils/api';
import { type CategoryRead, listManagedCategories } from '../utils/taxonomyApi';

const HEADLINE_ID = 'news-new-article-headline';
const SLUG_ID = 'news-new-article-slug';
const CATEGORY_ID = 'news-new-article-category';
const DATE_ID = 'news-new-article-date';

/** Today in the UTC calendar, which is the calendar `published_at` is stored in. */
function todayUtc(): string {
  return new Date().toISOString().slice(0, 10);
}

/** "New article" — headline, URL, category, date. All changeable later.
 *
 * The date defaults to today rather than to empty: an article with no date is
 * work in progress, and defaulting to that would make every new article land in
 * the undated pile whether or not its author meant it to.
 */
export function NewArticleDialog() {
  const [open, setOpen] = useState(false);
  const [headline, setHeadline] = useState('');
  // Null until edited: while null the slug tracks the headline, and the moment
  // an author types their own it stops being overwritten under them.
  const [slugOverride, setSlugOverride] = useState<string | null>(null);
  const [category, setCategory] = useState('');
  const [date, setDate] = useState(todayUtc);
  const [categories, setCategories] = useState<CategoryRead[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** The page a failed attempt already committed, kept so a retry adopts it
   *  instead of stranding another empty, articleless page in pagebuilder. */
  const [created, setCreated] = useState<{ id: number; slug: string } | null>(null);

  const slug = slugOverride ?? slugify(headline);

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
      setError(null);
      setCreated(null);
    }
  };

  const create = async () => {
    setPending(true);
    setError(null);
    try {
      // The page first: an article row is metadata *about* a page, so there is
      // nothing to attach to until one exists. A previous attempt's page is
      // adopted when the slug still matches — retrying otherwise creates a
      // second page and leaves the first orphaned.
      const pageId =
        created?.slug === slug ? created.id : await createArticlePage(headline.trim(), slug);
      setCreated({ id: pageId, slug });
      await attachArticle({
        page_id: pageId,
        category,
        published_at: date ? `${date}T00:00:00Z` : null,
      });
      router.visit(articleEditUrl(pageId), {
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
        <Button type="button">New article</Button>
      </DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (headline.trim() && slug && !pending) void create();
          }}
        >
          <DialogHeader>
            <DialogTitle>New article</DialogTitle>
            <DialogDescription>
              Four fields, all changeable later. Creating opens the editor for the body.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor={HEADLINE_ID}>Headline</Label>
              <Input
                id={HEADLINE_ID}
                value={headline}
                autoFocus
                disabled={pending}
                placeholder="Sensor rollout, north site"
                onChange={(e) => setHeadline(e.target.value)}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor={SLUG_ID}>URL</Label>
              <div className="flex items-center gap-1">
                <span className="text-sm text-muted-foreground">/p/</span>
                <Input
                  id={SLUG_ID}
                  value={slug}
                  disabled={pending}
                  onChange={(e) => setSlugOverride(e.target.value)}
                />
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor={CATEGORY_ID}>Category</Label>
              <NativeSelect
                id={CATEGORY_ID}
                value={category}
                disabled={pending}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">Uncategorised</option>
                {categories.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            </div>

            <div className="grid gap-2">
              <Label htmlFor={DATE_ID}>Publish date</Label>
              <Input
                id={DATE_ID}
                type="date"
                value={date}
                disabled={pending}
                onChange={(e) => setDate(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                A future date lists the article as scheduled. Clearing it makes it undated work in
                progress.
              </p>
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={() => reset(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !headline.trim() || !slug}>
              {pending ? 'Creating…' : 'Create draft'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
