import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { getArticleDetail, scheduleArticle } from '../../utils/api';

const GO_LIVE_ID = 'article-publish-at';
const COME_DOWN_ID = 'article-unpublish-at';

/** When an article goes live, and when it comes down.
 *
 * Its own card with its own Save rather than two more fields on the inspector,
 * for a reason that is not layout: scheduling is behind `news.publish` and the
 * rest of that panel is behind `news.edit`. Folded into the one Save, an author
 * who may write but not publish would get a 403 for the whole form — including
 * the byline they were actually trying to change.
 *
 * Distinct from the article's **display date** next door, which is editorial
 * metadata and may be in the past. These are instants with one job each, and
 * both are cleared the moment they are acted on.
 */
export function ScheduleCard({ articleId }: { articleId: number }) {
  const [publishAt, setPublishAt] = useState('');
  const [unpublishAt, setUnpublishAt] = useState('');
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  // Its own load, because these two live on the *detail* shape rather than the
  // listing one the screen already holds — deliberately, so a reader is never
  // told when a published article is due to come down.
  useEffect(() => {
    const controller = new AbortController();
    void getArticleDetail(articleId, controller.signal)
      .then((detail) => {
        setPublishAt(toLocalInput(detail.publish_at));
        setUnpublishAt(toLocalInput(detail.unpublish_at));
      })
      // Empty fields are the same as no schedule, which is the common case; a
      // failed read must not put an error box on a working editor.
      .catch(() => {});
    return () => controller.abort();
  }, [articleId]);

  const save = async () => {
    setBusy(true);
    try {
      await scheduleArticle(articleId, {
        // Empty clears it, which is a real instruction — an explicit null
        // rather than an omitted field, or cancelling would be unspellable.
        publish_at: publishAt ? new Date(publishAt).toISOString() : null,
        unpublish_at: unpublishAt ? new Date(unpublishAt).toISOString() : null,
      });
      setSaved(true);
      toast.success('Schedule saved');
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide">Schedule</h2>
        <span className="text-xs text-muted-foreground" aria-live="polite">
          {busy ? 'Saving…' : saved ? 'Saved' : ''}
        </span>
      </div>

      <div className="grid gap-2">
        <Label htmlFor={GO_LIVE_ID}>Go live</Label>
        <Input
          id={GO_LIVE_ID}
          type="datetime-local"
          value={publishAt}
          disabled={busy}
          onChange={(e) => setPublishAt(e.target.value)}
        />
      </div>

      <div className="grid gap-2">
        <Label htmlFor={COME_DOWN_ID}>Come down</Label>
        <Input
          id={COME_DOWN_ID}
          type="datetime-local"
          value={unpublishAt}
          disabled={busy}
          onChange={(e) => setUnpublishAt(e.target.value)}
        />
      </div>

      <p className="text-xs text-muted-foreground">
        Both are optional, and clearing one cancels it. The article changes state within a minute of
        the time you set, not exactly on it.
      </p>

      <Button className="w-full" variant="outline" disabled={busy} onClick={() => void save()}>
        Save schedule
      </Button>
    </div>
  );
}

/** An ISO instant as `datetime-local` wants it: local time, no zone, no seconds.
 *
 * Local rather than UTC on purpose. A `datetime-local` input has no timezone, so
 * whatever is typed is read as the editor's own clock — and an editor arranging
 * an embargo is thinking in their own working day, not in UTC. The value is
 * converted back on the way out, so the instant stored is unambiguous.
 */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return '';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  const shifted = new Date(at.getTime() - at.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}
