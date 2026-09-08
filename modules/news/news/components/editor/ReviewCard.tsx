import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useState } from 'react';
import { toast } from 'sonner';

import { type ArticleRead, approveArticle, rejectArticle, submitArticle } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';

/** The review step, for hosts that want one.
 *
 * `news.publish` exists to separate the person who writes an article from the
 * person who puts it in front of readers. The routes that make that real —
 * submit, approve, reject — were implemented and tested from the start and had
 * no screen, so the only way to use the separation the permission was created
 * for was to drive the API by hand.
 *
 * Which controls appear depends on both the article's state and the viewer's
 * permissions, because they are different jobs: an author submits, a reviewer
 * decides.
 *
 * Approving publishes in the same action, so this is where someone commits an
 * article to readers — and until the preview route existed, the only thing
 * they could look at first was the block canvas, an editor with drag handles
 * and editor chrome, which is not the article.
 *
 * The preview itself is not repeated here. This card renders on the article
 * screen, whose header already carries a Preview that is present in every
 * state; a second link to the same place a few hundred pixels below it is one
 * affordance wearing two buttons. The copy below points at it instead.
 */
export function ReviewCard({
  article,
  canPublish,
  onChanged,
}: {
  article: ArticleRead;
  canPublish: boolean;
  onChanged: () => Promise<void> | void;
}) {
  const { t } = useT();
  const copy = keys.news.review;
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState('');

  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await action();
      await onChanged();
      toast.success(done);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitted = article.status === 'submitted_for_review';

  // Nothing to offer: a published article has been through review, and an
  // author looking at someone else's submission has no decision to make.
  if (!submitted && article.status !== 'draft') return null;
  if (submitted && !canPublish) {
    return (
      <div className="rounded-lg border p-4">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide">{t(copy.heading)}</h2>
        <p className="mb-3 text-xs text-muted-foreground">{t(copy.with_reviewer)}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide">{t(copy.heading)}</h2>

      {submitted ? (
        <>
          <p className="text-xs text-muted-foreground">{t(copy.submitted)}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={busy}
              onClick={() => void run(() => approveArticle(article.id), t(copy.approved_toast))}
            >
              {t(copy.approve)}
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => setRejecting(true)}>
              {t(copy.send_back)}
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            {canPublish ? t(copy.can_publish) : t(copy.hand_over)}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void run(() => submitArticle(article.id), t(copy.submitted_toast))}
            >
              {t(copy.submit)}
            </Button>
          </div>
        </>
      )}

      <Dialog open={rejecting} onOpenChange={(next) => !busy && setRejecting(next)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t(copy.reject_title)}</DialogTitle>
            <DialogDescription>{t(copy.reject_description)}</DialogDescription>
          </DialogHeader>
          <Textarea
            rows={3}
            value={note}
            disabled={busy}
            aria-label={t(copy.reject_label)}
            placeholder={t(copy.reject_placeholder)}
            onChange={(e) => setNote(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setRejecting(false)}>
              {t(copy.cancel)}
            </Button>
            <Button
              disabled={busy}
              onClick={() =>
                void run(() => rejectArticle(article.id, note), t(copy.sent_back_toast)).then(
                  () => {
                    setRejecting(false);
                    setNote('');
                  },
                )
              }
            >
              {t(copy.send_back)}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
