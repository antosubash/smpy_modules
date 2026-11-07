import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@simple-module-py/ui/components/ui/alert-dialog';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { type ReactNode, useEffect, useRef, useState } from 'react';

import { useCampaignProgress } from '../../hooks/useCampaignProgress';
import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { daysLeft, formatWhen } from '../../utils/progress';
import type { CampaignDetail, Progress } from '../../utils/types';
import { STATUS_LABELS } from '../campaigns/CampaignTable';

const copy = keys.newsletter.sending;
const pausedKeys = copy.paused_code as Record<string, string>;

type Action = 'pause' | 'resume' | 'unschedule' | 'cancel';

/** What each status offers, in order. Cancel always asks first. */
const ACTIONS: Record<string, Action[]> = {
  scheduled: ['unschedule', 'cancel'],
  sending: ['pause', 'cancel'],
  paused: ['resume', 'cancel'],
};
/** Paused before it was ever frozen (at freeze: list gone, https required):
 * nothing was sent, so it can also go back to draft and be scheduled afresh. */
const PAUSED_UNSTARTED: Action[] = ['resume', 'unschedule', 'cancel'];

const CALLS: Record<Action, (c: CampaignDetail) => Promise<CampaignDetail>> = {
  pause: (c) => api.pauseCampaign(c.id),
  resume: (c) => api.resumeCampaign(c.id),
  cancel: (c) => api.cancelCampaign(c.id),
  unschedule: (c) => api.unscheduleCampaign(c.id, c.revision),
};

function actionsFor(campaign: CampaignDetail): Action[] {
  if (campaign.status === 'paused' && !campaign.started_at) return PAUSED_UNSTARTED;
  return ACTIONS[campaign.status] ?? [];
}

interface Props {
  campaign: CampaignDetail;
  canSend: boolean;
  onChange: (c: CampaignDetail) => void;
}

/** Where a non-draft campaign stands, and what can be done about it. Nothing for a draft. */
export function SendingPanel({ campaign, canSend, onChange }: Props) {
  const { t, locale } = useT();
  const { progress, error: progressError } = useCampaignProgress(campaign.id, campaign.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useFollowWorker(campaign, progress, onChange);

  if (campaign.status === 'draft') return null;
  const when = (iso: string) => formatWhen(iso, locale ?? 'en');

  const run = async (action: Action): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      onChange(await CALLS[action](campaign));
      return true;
    } catch (e) {
      setError(errorMessage(e, t));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const lines: ReactNode[] = [];
  const { status } = campaign;
  if (status === 'scheduled' && campaign.scheduled_at) {
    lines.push(t(copy.panel.scheduled_for, { date: when(campaign.scheduled_at) }));
  }
  if (status === 'sending' && progress) {
    lines.push(t(copy.panel.progress, { sent: progress.sent, total: progress.recipients }));
    const days = daysLeft(progress);
    if (days !== null && progress.estimated_finish) {
      const date = when(progress.estimated_finish);
      lines.push(t(copy.panel.eta, { date, count: days, rate: progress.daily_rate }));
    }
  }
  if (status === 'paused') {
    const code = campaign.paused_code;
    if (code) lines.push(Object.hasOwn(pausedKeys, code) ? t(pausedKeys[code]) : code);
    if (campaign.paused_detail) {
      lines.push(t(copy.panel.paused, { detail: campaign.paused_detail }));
    }
  }
  if (status === 'sent' || status === 'cancelled') {
    if (campaign.finished_at)
      lines.push(t(copy.panel.finished, { date: when(campaign.finished_at) }));
    const counts = copy.panel.counts;
    lines.push(
      [
        t(counts.failed, { count: campaign.failed_count }),
        t(counts.bounced, { count: campaign.bounced_count }),
        t(counts.suppressed, { count: campaign.suppressed_count }),
        t(counts.skipped, { count: progress?.skipped ?? 0 }),
        t(counts.unsubscribed, { count: campaign.unsubscribe_count }),
      ].join(' · '),
    );
  }

  const actions = canSend ? actionsFor(campaign) : [];
  return (
    <section className="flex flex-wrap items-center gap-3 border-b px-4 py-2 text-sm">
      <Badge variant="secondary">
        {Object.hasOwn(STATUS_LABELS, status) ? t(STATUS_LABELS[status]) : status}
      </Badge>
      <div className="min-w-0 flex-1 space-y-0.5">
        {lines.map((line, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: a fixed, ordered list of lines
          <p key={i}>{line}</p>
        ))}
        {(error ?? progressError) && (
          <p role="alert" className="text-destructive">
            {error ?? progressError}
          </p>
        )}
      </div>
      {actions.map((action) =>
        action === 'cancel' ? (
          <CancelButton key={action} busy={busy} error={error} onConfirm={() => run('cancel')} />
        ) : (
          <Button
            key={action}
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => void run(action)}
          >
            {t(copy.actions[action])}
          </Button>
        ),
      )}
    </section>
  );
}

/**
 * The worker moves a campaign on its own (scheduled -> sending, sending -> sent
 * or paused). When a poll answered *after* the page's copy last changed reports
 * another status, re-read the campaign so the lines and buttons follow it.
 * A poll from before that change (the answer still on screen) is ignored, and
 * a draft has nothing the worker can move.
 */
function useFollowWorker(
  campaign: CampaignDetail,
  progress: Progress | null,
  onChange: (c: CampaignDetail) => void,
) {
  const seen = useRef<{ status: string; stale: Progress | null } | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const { id, status } = campaign;
  useEffect(() => {
    if (seen.current?.status !== status) {
      seen.current = { status, stale: progress };
      return;
    }
    if (status === 'draft' || !progress || progress === seen.current.stale) return;
    if (progress.status === status) return;
    seen.current.stale = progress;
    api.getCampaign(id).then(
      (next) => onChangeRef.current(next),
      () => undefined, // the next poll tries again
    );
  }, [id, status, progress]);
}

interface CancelProps {
  busy: boolean;
  /** The last action's failure, shown in the dialog that stays open after it. */
  error: string | null;
  /** Resolves false when the cancel was refused. */
  onConfirm: () => Promise<boolean>;
}

/** "Cancel sending", behind a confirmation: unsent messages are dropped for good. */
function CancelButton({ busy, error, onConfirm }: CancelProps) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const confirm = copy.cancel_confirm;
  return (
    <AlertDialog open={open} onOpenChange={(next) => !busy && setOpen(next)}>
      <AlertDialogTrigger asChild>
        <Button size="sm" variant="outline" disabled={busy}>
          {t(copy.actions.cancel)}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t(confirm.title)}</AlertDialogTitle>
          <AlertDialogDescription>{t(confirm.description)}</AlertDialogDescription>
        </AlertDialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>{t(confirm.keep)}</AlertDialogCancel>
          <AlertDialogAction
            disabled={busy}
            className="bg-destructive text-white hover:bg-destructive/90"
            // Radix closes on click; here it closes only once the cancel went through.
            onClick={(e) => {
              e.preventDefault();
              void onConfirm().then((ok) => ok && setOpen(false));
            }}
          >
            {t(confirm.confirm)}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
