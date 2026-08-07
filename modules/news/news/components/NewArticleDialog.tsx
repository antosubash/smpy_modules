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
import { useState } from 'react';

import { attachArticle, createArticlePage } from '../utils/api';

const TITLE_INPUT_ID = 'news-new-article-title';

/** "New article" — asks for a title, then drops the author into the editor. */
export function NewArticleDialog() {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** The page a failed attempt already committed, kept so a retry adopts it
   *  instead of creating another. */
  const [created, setCreated] = useState<{ id: number; title: string } | null>(null);

  const reset = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setTitle('');
      setError(null);
      setCreated(null);
    }
  };

  const create = async () => {
    setPending(true);
    setError(null);
    try {
      // Create the page first: the article row is metadata *about* a page, so
      // there is nothing to attach to until one exists.
      //
      // Reuse the page a previous attempt committed. If `attachArticle` below
      // fails, the page it was attaching to already exists — and the slug
      // carries `Date.now()`, so nothing collides to stop a retry creating a
      // second one. Every press of "Create article" would otherwise strand
      // another empty, articleless page in pagebuilder. An edited title has
      // nothing to adopt, since the committed page carries the old one.
      const pageId =
        created?.title === title
          ? created.id
          : await createArticlePage(title, `${slugify(title)}-${Date.now()}`);
      setCreated({ id: pageId, title });
      await attachArticle({ page_id: pageId, category: '', published_at: null });
      router.visit(`/pagebuilder/${pageId}/edit`, {
        // A visit that lands unmounts this component, so this only fires when
        // one does not. Without it a failed navigation leaves the dialog on
        // "Creating…" with both buttons disabled, permanently — closing and
        // reopening does not clear it either, since the page and the article
        // both already exist by then.
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
            if (title.trim() && !pending) void create();
          }}
        >
          <DialogHeader>
            <DialogTitle>New article</DialogTitle>
            <DialogDescription>
              Creates a page and opens it in the editor. Set the category and date back here
              afterwards.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2 py-4">
            <Label htmlFor={TITLE_INPUT_ID}>Title</Label>
            <Input
              id={TITLE_INPUT_ID}
              value={title}
              autoFocus
              disabled={pending}
              placeholder="Field campaign in Estonia"
              onChange={(e) => setTitle(e.target.value)}
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={() => reset(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={pending || !title.trim()}>
              {pending ? 'Creating…' : 'Create article'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
