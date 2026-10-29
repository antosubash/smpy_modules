import { Head, router } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { ImagesLayout } from '../components/ImagesLayout';
import { ReviewPanel } from '../components/review/ReviewPanel';
import { useReviewKeys } from '../hooks/useReviewKeys';
import { useReviewQueue } from '../hooks/useReviewQueue';
import { listPrompts } from '../utils/api-prompts';
import type { ReviewAction, ReviewFilter } from '../utils/api-review';
import { keys, useT } from '../utils/i18n';
import type { Collection } from '../utils/types';
import type { Prompt } from '../utils/types-prompts';

const STATUSES = {
  unreviewed: keys.images.review.filter.unreviewed,
  accepted: keys.images.review.filter.accepted,
  corrected: keys.images.review.filter.corrected,
  rejected: keys.images.review.filter.rejected,
  all: keys.images.review.filter.all,
} satisfies Record<ReviewFilter, string>;

/** `Images/Review` - `/admin/images/{id}/review`. The queue of a collection's
 *  AI results: accept, correct (a form generated from the prompt's schema) or
 *  reject, with j/k/a/r/e. An editor's screen; the API refuses anyone else. */
function Review({ collection }: { collection: Collection }) {
  const { t } = useT();
  const [status, setStatus] = useState<ReviewFilter>('unreviewed');
  const [prompt, setPrompt] = useState<string | null>(null);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [index, setIndex] = useState(0);
  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const queue = useReviewQueue(collection.id, status, prompt);

  useEffect(() => {
    listPrompts(collection.id)
      .then(setPrompts)
      .catch(() => setPrompts([]));
  }, [collection.id]);

  const items = queue.items ?? [];
  const at = Math.min(index, Math.max(items.length - 1, 0));
  const item = items[at];
  const back = `/admin/images/${collection.id}`;

  const move = (to: number) => {
    setEditing(false);
    setFormError(null);
    setIndex(Math.max(0, Math.min(to, items.length - 1)));
    if (to >= items.length - 1 && queue.hasMore) queue.loadMore();
  };

  const act = async (action: ReviewAction, data?: Record<string, unknown>) => {
    if (!item || queue.busy) return;
    const { outcome, message } = await queue.review(item, action, data);
    if (outcome === 'saved') {
      toast(t(keys.images.review.saved));
      setEditing(false);
      setFormError(null);
      if (status !== 'unreviewed') setIndex(at + 1);
    } else if (outcome === 'stale') {
      toast.error(t(keys.images.review.stale));
      setEditing(false);
    } else {
      setFormError(message ?? null);
    }
  };

  useReviewKeys({
    editing,
    next: () => move(at + 1),
    previous: () => move(at - 1),
    accept: () => void act('accept'),
    reject: () => void act('reject'),
    edit: () => item && setEditing(true),
    cancel: () => setEditing(false),
  });

  return (
    <>
      <Head title={t(keys.images.review.title)} />
      <PageShell
        title={t(keys.images.review.title)}
        description={collection.name}
        back={back}
        actions={
          <Button type="button" variant="outline" onClick={() => router.visit(back)}>
            {t(keys.images.review.back)}
          </Button>
        }
      >
        <div className="space-y-6">
          <div className="flex flex-wrap items-end gap-4">
            <div className="grid gap-2">
              <Label htmlFor="images-review-status">{t(keys.images.review.filter.status)}</Label>
              <NativeSelect
                id="images-review-status"
                data-testid="images-review-status-filter"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value as ReviewFilter);
                  setIndex(0);
                  setEditing(false);
                }}
              >
                {(Object.keys(STATUSES) as ReviewFilter[]).map((s) => (
                  <option key={s} value={s}>
                    {t(STATUSES[s])}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="images-review-prompt">{t(keys.images.review.filter.prompt)}</Label>
              <NativeSelect
                id="images-review-prompt"
                data-testid="images-review-prompt-filter"
                value={prompt ?? ''}
                onChange={(e) => {
                  setPrompt(e.target.value || null);
                  setIndex(0);
                  setEditing(false);
                }}
              >
                <option value="">{t(keys.images.review.filter.all_prompts)}</option>
                {prompts.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            {item && (
              <span
                className="pb-2 text-sm text-muted-foreground"
                data-testid="images-review-position"
              >
                {t(keys.images.review.position, { n: at + 1, total: items.length })}
                {queue.hasMore ? '+' : ''}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{t(keys.images.review.keys)}</p>
          {queue.error && <p className="text-sm text-destructive">{queue.error}</p>}
          {queue.items === null && !queue.error && (
            <p className="text-sm text-muted-foreground">{t(keys.images.review.loading)}</p>
          )}
          {queue.items !== null && !item && (
            <p className="text-sm text-muted-foreground" data-testid="images-review-empty">
              {t(keys.images.review.empty)}
            </p>
          )}
          {item && (
            <ReviewPanel
              item={item}
              editing={editing}
              busy={queue.busy}
              formError={formError}
              onAction={(a) => void act(a)}
              onEdit={() => setEditing(true)}
              onCancel={() => setEditing(false)}
              onCorrect={(data) => void act('correct', data)}
            />
          )}
        </div>
      </PageShell>
    </>
  );
}

Review.layout = [ImagesLayout];
export default Review;
