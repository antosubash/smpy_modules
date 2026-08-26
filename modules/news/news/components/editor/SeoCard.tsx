import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { getArticleDetail, updateArticle } from '../../utils/api';

const DESC_ID = 'article-meta-description';
const IMAGE_ID = 'article-og-image';
const CANONICAL_ID = 'article-canonical-url';
const INDEX_ID = 'article-index-in-search';

/** How the article looks in a search result and a shared link.
 *
 * These columns existed, the API accepted them and the viewer rendered them —
 * but nothing in the console set them, so the description was only ever
 * whatever the migration carried over from the page an article used to be. The
 * one field a newsroom actually reaches for was unreachable.
 *
 * Its own card with its own load and Save because these live on the *detail*
 * shape rather than the listing one the screen already holds. Folding five more
 * fields into the inspector's draft would mean the main form fetching a second
 * document just to render a panel most edits never touch.
 */
export function SeoCard({ articleId }: { articleId: number }) {
  const [description, setDescription] = useState('');
  const [image, setImage] = useState('');
  const [canonical, setCanonical] = useState('');
  const [indexed, setIndexed] = useState(true);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void getArticleDetail(articleId, controller.signal)
      .then((detail) => {
        setDescription(detail.meta_description ?? '');
        setImage(detail.og_image ?? '');
        setCanonical(detail.canonical_url ?? '');
        setIndexed(detail.index_in_search);
      })
      .catch(() => {});
    return () => controller.abort();
  }, [articleId]);

  const save = async () => {
    setBusy(true);
    try {
      await updateArticle(articleId, {
        meta_description: description,
        og_image: image,
        canonical_url: canonical,
        index_in_search: indexed,
      });
      setSaved(true);
      toast.success('Search settings saved');
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide">Search &amp; sharing</h2>
        <span className="text-xs text-muted-foreground" aria-live="polite">
          {busy ? 'Saving…' : saved ? 'Saved' : ''}
        </span>
      </div>

      <div className="grid gap-2">
        <Label htmlFor={DESC_ID}>Summary</Label>
        <Textarea
          id={DESC_ID}
          rows={3}
          value={description}
          disabled={busy}
          onChange={(e) => setDescription(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Shown under the headline in a search result and in a shared link. Also the excerpt in the
          archive and in feed blocks, so it is worth writing even for a site nobody searches.
        </p>
      </div>

      <div className="grid gap-2">
        <Label htmlFor={IMAGE_ID}>Share image URL</Label>
        <Input
          id={IMAGE_ID}
          value={image}
          disabled={busy}
          placeholder="https://…"
          onChange={(e) => setImage(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          The picture a link preview shows, and the cover at the top of the article.
        </p>
      </div>

      <div className="grid gap-2">
        <Label htmlFor={CANONICAL_ID}>Canonical URL</Label>
        <Input
          id={CANONICAL_ID}
          value={canonical}
          disabled={busy}
          placeholder="Leave blank to use this article's own address"
          onChange={(e) => setCanonical(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          Only for an article republished from somewhere else — it points search engines at the
          original instead of this copy.
        </p>
      </div>

      <div className="flex items-start gap-2">
        <Checkbox
          id={INDEX_ID}
          checked={indexed}
          disabled={busy}
          onCheckedChange={(checked) => setIndexed(checked === true)}
        />
        <div className="grid gap-0.5">
          <Label htmlFor={INDEX_ID}>Allow search engines to index it</Label>
          <p className="text-xs text-muted-foreground">
            Off sends <code>noindex</code> and drops the article from the sitemap. It stays readable
            to anyone with the link.
          </p>
        </div>
      </div>

      <Button className="w-full" variant="outline" disabled={busy} onClick={() => void save()}>
        Save search settings
      </Button>
    </div>
  );
}
