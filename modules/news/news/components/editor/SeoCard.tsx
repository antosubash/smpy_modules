import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { getArticleDetail, updateArticle } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';

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
  const { t } = useT();
  const copy = keys.news.seo;
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
      toast.success(t(copy.saved_toast));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide">{t(copy.heading)}</h2>
        <span className="text-xs text-muted-foreground" aria-live="polite">
          {busy ? t(copy.saving) : saved ? t(copy.saved) : ''}
        </span>
      </div>

      <div className="grid gap-2">
        <Label htmlFor={DESC_ID}>{t(copy.summary_label)}</Label>
        <Textarea
          id={DESC_ID}
          rows={3}
          value={description}
          disabled={busy}
          onChange={(e) => setDescription(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">{t(copy.summary_help)}</p>
      </div>

      <div className="grid gap-2">
        <Label htmlFor={IMAGE_ID}>{t(copy.image_label)}</Label>
        <Input
          id={IMAGE_ID}
          value={image}
          disabled={busy}
          placeholder={t(copy.image_placeholder)}
          onChange={(e) => setImage(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">{t(copy.image_help)}</p>
      </div>

      <div className="grid gap-2">
        <Label htmlFor={CANONICAL_ID}>{t(copy.canonical_label)}</Label>
        <Input
          id={CANONICAL_ID}
          value={canonical}
          disabled={busy}
          placeholder={t(copy.canonical_placeholder)}
          onChange={(e) => setCanonical(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">{t(copy.canonical_help)}</p>
      </div>

      <div className="flex items-start gap-2">
        <Checkbox
          id={INDEX_ID}
          checked={indexed}
          disabled={busy}
          onCheckedChange={(checked) => setIndexed(checked === true)}
        />
        <div className="grid gap-0.5">
          <Label htmlFor={INDEX_ID}>{t(copy.index_label)}</Label>
          {/* The directive is a placeholder rather than a <code> splicing two
              translated halves together — one sentence, one catalogue entry. */}
          <p className="text-xs text-muted-foreground">
            {t(copy.index_help, { directive: 'noindex' })}
          </p>
        </div>
      </div>

      <Button className="w-full" variant="outline" disabled={busy} onClick={() => void save()}>
        {t(copy.save)}
      </Button>
    </div>
  );
}
