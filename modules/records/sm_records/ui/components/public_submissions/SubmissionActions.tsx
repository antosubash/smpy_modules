import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';
import { toast } from 'sonner';
import { ApiError } from '../../utils/api';
import { markNotSpam, markSpam, resendNotification } from '../../utils/api-submissions';
import { keys, type Translate, useT } from '../../utils/i18n';
import type { RecordRead, TypeRead } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';

type SpamReason = 'links' | 'manual';

const REASONS: Record<SpamReason, string> = {
  links: keys.records.public_submissions.actions.spam_reason.links,
  manual: keys.records.public_submissions.actions.spam_reason.manual,
};

/** What to tell the admin, in their language. The server's `detail` is
 *  English; the two refusals an editor meets in practice get a sentence of
 *  their own, and anything else is quoted after a translated lead-in. */
function explain(t: Translate, err: unknown): string {
  const a = keys.records.public_submissions.actions;
  if (err instanceof ApiError && err.status === 429) return t(a.rate_limited);
  if (err instanceof ApiError && (err.status === 404 || err.status === 409)) return t(a.stale);
  return t(a.failed, { message: err instanceof Error ? err.message : String(err) });
}

/**
 * Resend / Mark as spam / Not spam for a contact-form submission (#101).
 *
 * The trash is the spam folder: *Mark as spam* trashes the record with
 * `sm_spam = "manual"`, and a record in the trash that carries a spam mark
 * (by hand, or `links` from the server's heuristic) offers *Not spam*, which
 * restores it and sends the notification it never got. Both hand the record
 * the server returns to `onChanged`, so the editor shows its new state in
 * place. *Resend* is for a record whose notification was not sent.
 */
export function SubmissionActions({
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
  const spam = data.sm_spam as SpamReason | null | undefined;
  const notifies = (type.public_submissions?.notify_to ?? []).length > 0;

  const resend = async () => {
    setBusy(true);
    try {
      await resendNotification(type.key, record.uuid);
      toast.success(t(a.resent));
    } catch (err) {
      toast.error(explain(t, err));
    } finally {
      setBusy(false);
    }
  };

  const notSpam = async () => {
    setBusy(true);
    try {
      onChanged(await markNotSpam(type.key, record.uuid));
      toast.success(t(a.not_spam_done));
    } catch (err) {
      toast.error(explain(t, err));
    } finally {
      setBusy(false);
    }
  };

  if (record.is_deleted) {
    if (!spam) return null;
    return (
      <div className="flex flex-wrap items-center gap-2" data-testid="records-submission-actions">
        <span className="text-sm text-muted-foreground">
          {t(a.is_spam, { reason: REASONS[spam] ? t(REASONS[spam]) : spam })}
        </span>
        <Button type="button" variant="outline" disabled={busy} onClick={() => void notSpam()}>
          {t(a.not_spam)}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="records-submission-actions">
      {notifies && !data.sm_notified_at && (
        <span className="text-sm text-destructive" data-testid="records-submission-not-sent">
          {t(a.not_sent)}
        </span>
      )}
      {notifies && (
        <Button type="button" variant="outline" disabled={busy} onClick={() => void resend()}>
          {t(a.resend)}
        </Button>
      )}
      <ConfirmDialog
        trigger={
          <Button type="button" variant="outline" disabled={busy}>
            {t(a.spam)}
          </Button>
        }
        title={t(a.spam_confirm_title)}
        description={t(a.spam_confirm_body)}
        confirmLabel={t(a.spam)}
        destructive
        onConfirm={async () => {
          try {
            onChanged(await markSpam(type.key, record.uuid));
          } catch (err) {
            // The dialog shows the message; make it the translated one.
            throw new Error(explain(t, err));
          }
          toast.success(t(a.spam_done));
        }}
      />
    </div>
  );
}
