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
import { useState } from 'react';

import { createArticleWithPage } from '../utils/api';

const TITLE_INPUT_ID = 'news-new-article-title';

/** "New article" — asks for a title, then drops the author into the editor. */
export function NewArticleDialog() {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setTitle('');
      setError(null);
    }
  };

  const create = async () => {
    setPending(true);
    setError(null);
    try {
      // One request: the server creates the page and attaches the article in a
      // single transaction. This used to be two calls from here — creating the
      // page through pagebuilder's API and then attaching — which needed both a
      // borrowed CSRF cookie and a `created` state to remember the page a
      // failed attempt had already committed, so a retry adopted it instead of
      // stranding another empty page. Neither is reachable any more: a failure
      // now leaves nothing behind to adopt.
      const article = await createArticleWithPage({ title });
      if (article === null) throw new Error('The server did not return the new article.');
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
