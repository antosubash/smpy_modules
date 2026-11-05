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
import { type ReactNode, useState } from 'react';

import { useCampaignProgress } from '../../hooks/useCampaignProgress';
import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { daysLeft, formatWhen } from '../../utils/progress';
import type { CampaignDetail } from '../../utils/types';

const copy = keys.newsletter.sending;
const statusKeys = keys.newsletter.campaigns.status as Record<string, string>;
const pausedKeys = copy.paused_code as Record<string, string>;

type Action = 'pause' | 'resume' | 'unschedule' | 'cancel';

/** What each status offers, in order. Cancel always asks first. */
const ACTIONS: Record<string, Action[]> = {
  scheduled: ['unschedule', 'cancel'],
  sending: ['pause', 'cancel'],
  paused: ['resume', 'cancel'],
};

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

  if (campaign.status === 'draft') return null;
  const when = (iso: string) => formatWhen(iso, locale ?? 'en');

  const run = async (action: Action): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      const id = campaign.id;
      const next =
        action === 'pause'
          ? await api.pauseCampaign(id)
          : action === 'resume'
            ? await api.resumeCampaign(id)
            : action === 'cancel'
              ? await api.cancelCampaign(id)
              : await api.unscheduleCampaign(id, campaign.revision);
      onChange(next);
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
      lines.push(t(copy.panel.eta, { date, days, rate: progress.daily_rate }));
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

  const actions = canSend ? (ACTIONS[status] ?? []) : [];
  return (
    <section className="flex flex-wrap items-center gap-3 border-b px-4 py-2 text-sm">
      <Badge variant="secondary">
        {Object.hasOwn(statusKeys, status) ? t(statusKeys[status]) : status}
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
          <CancelButton key={action} busy={busy} onConfirm={() => run('cancel')} />
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

/** "Cancel sending", behind a confirmation: unsent messages are dropped for good. */
function CancelButton({ busy, onConfirm }: { busy: boolean; onConfirm: () => Promise<boolean> }) {
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
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>{t(confirm.keep)}</AlertDialogCancel>
          <AlertDialogAction
            disabled={busy}
            className="bg-destructive text-white hover:bg-destructive/90"
            // Radix closes on click; it closes here only once the request is done.
            onClick={(e) => {
              e.preventDefault();
              void onConfirm().then(() => setOpen(false));
            }}
          >
            {t(confirm.confirm)}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
