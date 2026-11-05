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
import { RadioGroup, RadioGroupItem } from '@simple-module-py/ui/components/ui/radio-group';
import { useCallback, useEffect, useState } from 'react';

import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { formatWhen, toUtcIso } from '../../utils/progress';
import type { CampaignDetail, Estimate } from '../../utils/types';

const copy = keys.newsletter.sending.dialog;
const AT_ID = 'newsletter-send-at';

type When = 'now' | 'later';

interface Props {
  campaign: CampaignDetail;
  /** The page's `can_send`: without it there is no trigger at all. */
  canSend: boolean;
  onSent: (c: CampaignDetail) => void;
  /** The editor's `flush`: saves what is pending; false when anything stayed unsaved. */
  flush: () => Promise<boolean>;
  dirty: boolean;
  incomplete: boolean;
  /** The revision the editor's last save produced. */
  currentRevision: () => number;
}

/** Now, or a time; `scheduled` is null for now *and* for a later time that is not a
 *  real future instant, so `when` is what tells them apart. */
interface Choice {
  when: When;
  scheduled: string | null;
}

const inFuture = (iso: string | null): iso is string =>
  iso !== null && Date.parse(iso) > Date.now();

/** A future `datetime-local` value as ISO UTC, else null. */
function futureIso(local: string): string | null {
  const iso = toUtcIso(local);
  return inFuture(iso) ? iso : null;
}

/** "Send…": now or at a time, with the recipients and when it should finish.
 *
 * Opening saves the pending autosave first; Confirm saves again and checks, once
 * React has rendered what that save changed, that nothing is still unsaved or
 * unfinished, then posts with the revision the final save produced (A8).
 */
export function SendDialog(props: Props) {
  const { campaign, canSend, onSent, flush, dirty, incomplete, currentRevision } = props;
  const { t, locale } = useT();
  const [open, setOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const [when, setWhen] = useState<When>('now');
  const [at, setAt] = useState('');
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [pending, setPending] = useState(false);
  /** What Confirm chose, set once its flush resolved true; the post waits for the
   *  render after it and sends only this, never a value recomputed since. */
  const [armed, setArmed] = useState<Choice | null>(null);
  const [error, setError] = useState<string | null>(null);

  const scheduledAt = when === 'later' ? futureIso(at) : null;
  const blocked = when === 'later' && scheduledAt === null;
  const timePast = blocked && at !== '';

  const refuse = useCallback(
    (key: string) => {
      setError(t(key));
      setPending(false);
    },
    [t],
  );

  const change = async (next: boolean) => {
    if (pending) return;
    setOpen(next);
    setReady(false);
    setError(null);
    setEstimate(null);
    if (!next) return;
    // Every opening starts at "now": a time kept from an earlier opening (or from a
    // schedule since undone) would otherwise go out as a schedule nobody chose this time.
    setWhen('now');
    setAt('');
    if (await flush()) setReady(true);
    else refuse(copy.unsaved);
  };

  useEffect(() => {
    if (!open || !ready || (when === 'later' && scheduledAt === null)) return;
    let live = true;
    api.estimate(campaign.id, scheduledAt).then(
      (e) => live && setEstimate(e),
      (e) => live && setError(errorMessage(e, t)),
    );
    return () => {
      live = false;
    };
  }, [open, ready, when, scheduledAt, campaign.id, t]);

  const post = useCallback(
    async (revision: number, scheduled: string | null) => {
      try {
        const sent = await api.sendCampaign(campaign.id, {
          expected_revision: revision,
          scheduled_at: scheduled,
        });
        setOpen(false);
        onSent(sent);
      } catch (e) {
        setError(errorMessage(e, t)); // a 409 `stale` says to reload
      } finally {
        setPending(false);
      }
    },
    [campaign.id, onSent, t],
  );

  // After the render that carries the final save's state, so `dirty` and
  // `incomplete` here are what that save left behind, not what Confirm saw.
  // A later time that slipped into the past while the save ran is refused, never
  // sent as "now" (whose `scheduled_at` is null too).
  useEffect(() => {
    if (!armed) return;
    setArmed(null);
    if (dirty || incomplete) refuse(copy.unsaved);
    else if (armed.when === 'later' && !inFuture(armed.scheduled)) refuse(copy.time_past);
    else void post(currentRevision(), armed.when === 'later' ? armed.scheduled : null);
  }, [armed, dirty, incomplete, refuse, post, currentRevision]);

  const confirm = async () => {
    const choice: Choice = { when, scheduled: when === 'later' ? futureIso(at) : null };
    if (choice.when === 'later' && choice.scheduled === null) return refuse(copy.time_past);
    setPending(true);
    setError(null);
    if (await flush()) setArmed(choice);
    else refuse(copy.unsaved);
  };

  if (!canSend || campaign.status !== 'draft') return null;

  return (
    <Dialog open={open} onOpenChange={(next) => void change(next)}>
      <DialogTrigger asChild>
        <Button
          type="button"
          size="sm"
          disabled={incomplete}
          title={incomplete ? t(copy.incomplete) : undefined}
        >
          {t(keys.newsletter.sending.send_button)}
        </Button>
      </DialogTrigger>
      {incomplete && <span className="sr-only">{t(copy.incomplete)}</span>}
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t(copy.title)}</DialogTitle>
          <DialogDescription>{t(copy.description, { name: campaign.name })}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 py-2">
          <RadioGroup value={when} onValueChange={(v) => setWhen(v as When)} disabled={pending}>
            {(['now', 'later'] as const).map((id) => (
              <div key={id} className="flex items-center gap-2">
                <RadioGroupItem id={`newsletter-send-${id}`} value={id} />
                <Label htmlFor={`newsletter-send-${id}`}>{t(copy[id])}</Label>
              </div>
            ))}
          </RadioGroup>
          {when === 'later' && (
            <div className="grid gap-1">
              <Label htmlFor={AT_ID}>{t(copy.at_label)}</Label>
              <Input
                id={AT_ID}
                type="datetime-local"
                value={at}
                disabled={pending}
                onChange={(e) => setAt(e.target.value)}
              />
              {timePast && <p className="text-sm text-destructive">{t(copy.time_past)}</p>}
            </div>
          )}
          {estimate && !blocked && (
            <div className="space-y-1 text-sm">
              <p>{t(copy.recipients, { count: estimate.recipients })}</p>
              <p>
                {t(copy.estimate, { date: formatWhen(estimate.estimated_finish, locale ?? 'en') })}
              </p>
              {estimate.overlaps && <p className="text-amber-900">{t(copy.overlap)}</p>}
            </div>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={pending}
            onClick={() => void change(false)}
          >
            {t(copy.cancel)}
          </Button>
          <Button
            type="button"
            disabled={pending || blocked || !ready || !estimate}
            onClick={() => void confirm()}
          >
            {pending ? t(copy.sending) : t(copy.confirm)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
