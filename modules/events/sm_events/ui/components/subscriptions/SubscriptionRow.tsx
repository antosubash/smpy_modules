import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { failureText, type Subscription } from '../../utils/api-subscriptions';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';
import { ConfirmDialog } from '../ConfirmDialog';

type Props = {
  sub: Subscription;
  calendarColor: string;
  error: string | undefined;
  onAction: (action: 'refresh' | 'pause' | 'resume' | 'delete') => Promise<void>;
  onEdit: () => void;
};

/** The reasons items were left out, as words ("unknown time zone (10), unsupported repeat rule (2)"). */
function skipped(sub: Subscription, t: ReturnType<typeof useT>['t']): string | null {
  const total = sub.last_counts.skipped ?? 0;
  if (!total) return null;
  const copy = keys.events.subscriptions;
  const known = copy.skip as Record<string, string>;
  const reasons = Object.entries(sub.last_counts.reasons ?? {})
    .map(([code, count]) =>
      t(copy.row.skipped_reason, { reason: t(known[code] ?? copy.skip.other), count }),
    )
    .join(', ');
  return `${t(copy.row.skipped, { count: total })}: ${reasons}`;
}

export function SubscriptionRow({ sub, calendarColor, error, onAction, onEdit }: Props) {
  const { t, locale } = useT();
  const copy = keys.events.subscriptions;
  const when = (iso: string) => new Date(iso).toLocaleString(locale);
  const left = skipped(sub, t);
  const paused = sub.status === 'paused';
  return (
    <li className="space-y-1 rounded border p-3 text-sm" data-testid="subscription-row">
      <div className="flex flex-wrap items-center gap-2">
        <span
          aria-hidden="true"
          className="inline-block size-3 rounded-full border"
          style={{ backgroundColor: sub.color ?? calendarColor }}
        />
        <strong>
          <Name>{sub.label}</Name>
        </strong>
        <Badge
          variant={sub.status === 'ok' ? 'secondary' : 'outline'}
          data-testid="subscription-status"
        >
          {t(copy.status[sub.status])}
        </Badge>
        {sub.public ? <Badge variant="outline">{t(keys.events.visibility.public)}</Badge> : null}
      </div>
      <p className="font-mono text-xs break-all" data-testid="subscription-url">
        {sub.url_display}
      </p>
      <p className="text-muted-foreground">
        {sub.last_ok_at
          ? t(copy.row.updated, { when: when(sub.last_ok_at) })
          : t(copy.row.never_updated)}
        {' · '}
        {t(copy.row.events_count, { count: sub.item_count })}
        {sub.next_fetch_at && !paused
          ? ` · ${t(copy.row.next_refresh, { when: when(sub.next_fetch_at) })}`
          : ''}
      </p>
      {sub.error_code ? (
        <p role="status" className="text-destructive" data-testid="subscription-code">
          {failureText(sub.error_code, sub.last_http_status)}
        </p>
      ) : null}
      {left ? <p className="text-muted-foreground">{left}</p> : null}
      {sub.uses_internal_addresses ? (
        <p className="text-muted-foreground">{t(copy.row.internal)}</p>
      ) : null}
      {error ? (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2 pt-1">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={paused}
          aria-label={t(copy.refresh_for, { name: sub.label })}
          onClick={() => void onAction('refresh')}
        >
          {t(copy.refresh)}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-label={t(paused ? copy.resume_for : copy.pause_for, { name: sub.label })}
          onClick={() => void onAction(paused ? 'resume' : 'pause')}
        >
          {t(paused ? copy.resume : copy.pause)}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          aria-label={t(copy.edit_for, { name: sub.label })}
          onClick={onEdit}
        >
          {t(copy.edit)}
        </Button>
        <ConfirmDialog
          trigger={
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label={t(copy.remove_for, { name: sub.label })}
            >
              {t(copy.remove)}
            </Button>
          }
          title={t(copy.remove_title, { name: sub.label })}
          description={t(copy.remove_description, { count: sub.item_count })}
          confirmLabel={t(copy.remove)}
          onConfirm={() => onAction('delete')}
        />
      </div>
    </li>
  );
}
