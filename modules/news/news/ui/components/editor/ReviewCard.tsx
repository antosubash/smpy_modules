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
import type { ArticleWrite } from '../../hooks/useArticleEditor';
import { useInFlight } from '../../hooks/useInFlight';
import {
  type ArticleRead,
  approveArticle,
  rejectArticle,
  submitArticle,
  unpublishArticle,
} from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { ConfirmDialog } from '../ConfirmDialog';

/** How long the card stays inert after a transition. The next action appears
 *  under the pointer — Submit becomes Approve — so a double click must not be
 *  able to land on it. */
const TRANSITION_COOLDOWN_MS = 800;

/** The server's bound on a send-back note. */
const MAX_NOTE_LEN = 2000;

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
  writeArticle,
  conflict = false,
}: {
  article: ArticleRead;
  canPublish: boolean;
  writeArticle: ArticleWrite;
  /** The editor is blocked on a stale-write conflict (every write is refused
   *  until Reload), so the action may fail without ever reaching the server. */
  conflict?: boolean;
}) {
  const { t } = useT();
  const copy = keys.news.review;
  const { busy, run: guard } = useInFlight(TRANSITION_COOLDOWN_MS);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState('');

  /** Resolves `true` when the transition went through. On failure, resolves the
   *  server's own message (the 409 conflict text, a 403), so a caller can keep
   *  its dialog open and say why instead of a generic line, and keep a typed
   *  note. */
  const attempt = async (
    action: (version: string | null) => Promise<ArticleRead | null>,
    done: string,
  ): Promise<true | string> => {
    const failure: { reason: string | null } = { reason: null };
    const ok = await guard(async () => {
      try {
        const written = await writeArticle(async (version) => {
          try {
            return await action(version);
          } catch (e) {
            failure.reason = (e as Error).message;
            throw e;
          }
        });
        if (!written) {
          // The action never ran when the editor is already blocked on a
          // conflict, so the reason is that conflict.
          failure.reason ??= conflict ? t(keys.news.errors.article_conflict) : null;
          return false;
        }
        toast.success(done);
        return true;
      } catch (e) {
        toast.error((e as Error).message);
        failure.reason = (e as Error).message;
        return false;
      }
    });
    return ok === true ? true : (failure.reason ?? t(copy.unpublish_failed));
  };
  const run = async (
    action: (version: string | null) => Promise<ArticleRead | null>,
    done: string,
  ): Promise<boolean> => (await attempt(action, done)) === true;

  const submitted = article.status === 'submitted_for_review';

  // Nothing to offer: a published article has been through review, and an
  // author looking at someone else's submission has no decision to make.
  if (article.status === 'published') {
    // Only for someone who may publish: the route is behind `news.publish`.
    if (!canPublish) return null;
    return (
      <div className="space-y-3 rounded-lg border p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide">{t(copy.heading)}</h2>
        <p className="text-xs text-muted-foreground">{t(copy.published_help)}</p>
        <ConfirmDialog
          level="medium"
          title={t(copy.unpublish_title, { title: article.title })}
          description={t(copy.unpublish_description)}
          confirmLabel={t(copy.unpublish)}
          onConfirm={async () => {
            const result = await attempt(
              (version) => unpublishArticle(article.id, version),
              t(copy.unpublished_toast),
            );
            // The toast has already said why; throwing keeps the dialog open
            // and shows the same reason inside it.
            if (result !== true) throw new Error(result);
          }}
          trigger={
            <Button size="sm" variant="outline" disabled={busy}>
              {t(copy.unpublish)}
            </Button>
          }
        />
      </div>
    );
  }
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
              onClick={() =>
                void run((version) => approveArticle(article.id, version), t(copy.approved_toast))
              }
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
              onClick={() =>
                void run((version) => submitArticle(article.id, version), t(copy.submitted_toast))
              }
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
            maxLength={MAX_NOTE_LEN}
            disabled={busy}
            aria-label={t(copy.reject_label)}
            placeholder={t(copy.reject_placeholder)}
            onChange={(e) => setNote(e.target.value)}
          />
          <p className="text-right text-xs text-muted-foreground">
            {t(copy.note_count, { count: note.length, max: MAX_NOTE_LEN })}
          </p>
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setRejecting(false)}>
              {t(copy.cancel)}
            </Button>
            <Button
              disabled={busy}
              onClick={() =>
                void run(
                  (version) => rejectArticle(article.id, note, version),
                  t(copy.sent_back_toast),
                ).then((ok) => {
                  // Only on success: a failed send-back keeps the dialog and
                  // the note, so a long note is not lost to a server refusal.
                  if (!ok) return;
                  setRejecting(false);
                  setNote('');
                })
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
