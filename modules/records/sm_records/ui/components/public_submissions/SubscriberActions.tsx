import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';
import { toast } from 'sonner';
import { ApiError } from '../../utils/api';
import { resendConfirmation, unsubscribeSubscriber } from '../../utils/api-submissions';
import { keys, type Translate, useT } from '../../utils/i18n';
import type { RecordRead, TypeRead } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';

function explain(t: Translate, err: unknown): string {
  const a = keys.records.public_submissions.actions;
  if (err instanceof ApiError && err.status === 429) return t(a.confirmation_limited);
  if (err instanceof ApiError && (err.status === 404 || err.status === 409)) return t(a.stale);
  return t(a.failed, { message: err instanceof Error ? err.message : String(err) });
}

/**
 * Resend confirmation / Unsubscribe for a newsletter subscriber (#101).
 *
 * *Resend confirmation* is offered while the address is `pending`, with a
 * "not sent" badge when no confirmation has gone out. *Unsubscribe* does what
 * the subscriber's own link does: the address stays as a suppression record,
 * the consent proof is cleared and every link sent before stops working.
 */
export function SubscriberActions({
  type,
  record,
  onChanged,
}: {
  type: TypeRead;
  record: RecordRead;
  onChanged: (record: RecordRead) => void;
}) {
  const { t } = useT();
  const a = keys.records.public_submissions.actions;
  const [busy, setBusy] = useState(false);
  const data = (record.data ?? {}) as Record<string, unknown>;
  const status = data.sm_status as string | null | undefined;
  if (record.is_deleted || status === 'unsubscribed') return null;

  const resend = async () => {
    setBusy(true);
    try {
      await resendConfirmation(type.key, record.uuid);
      toast.success(t(a.resent_confirmation));
    } catch (err) {
      toast.error(explain(t, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="records-subscriber-actions">
      {status === 'pending' && !data.sm_confirm_sent_at && (
        <span className="text-sm text-destructive" data-testid="records-confirmation-not-sent">
          {t(a.confirmation_not_sent)}
        </span>
      )}
      {status === 'pending' && (
        <Button type="button" variant="outline" disabled={busy} onClick={() => void resend()}>
          {t(a.resend_confirmation)}
        </Button>
      )}
      <ConfirmDialog
        trigger={
          <Button type="button" variant="outline" disabled={busy}>
            {t(a.unsubscribe)}
          </Button>
        }
        title={t(a.unsubscribe_confirm_title)}
        description={t(a.unsubscribe_confirm_body)}
        confirmLabel={t(a.unsubscribe)}
        destructive
        onConfirm={async () => {
          try {
            onChanged(await unsubscribeSubscriber(type.key, record.uuid));
          } catch (err) {
            throw new Error(explain(t, err));
          }
          toast.success(t(a.unsubscribe_done));
        }}
      />
    </div>
  );
}
