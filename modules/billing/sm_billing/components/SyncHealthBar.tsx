import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { formatDate } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { SyncHealth } from '../utils/types';

/**
 * How stale the local mirror of Stripe may be (#122): the oldest
 * ``synced_at``, the webhook rows still unprocessed, and whether the periodic
 * reconcile is on. A missed webhook shows up here before a customer reports it.
 */
export function SyncHealthBar({ health }: { health: SyncHealth }) {
  const { t } = useT();
  const c = keys.billing.sync_health;
  const minutes = health.reconcile_interval_minutes;
  const reconcile =
    minutes <= 0
      ? t(c.reconcile_off)
      : health.reconcile_running
        ? t(c.reconcile_every, { minutes })
        : t(c.reconcile_not_running);
  return (
    <section
      aria-label={t(c.title)}
      className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground"
    >
      <span>
        {health.oldest_synced_at
          ? t(c.oldest_synced, { date: formatDate(health.oldest_synced_at) })
          : t(c.nothing_synced)}
      </span>
      {health.never_synced > 0 && (
        <Badge variant="outline">{t(c.never_synced, { count: health.never_synced })}</Badge>
      )}
      {health.unprocessed_webhooks > 0 ? (
        <Badge variant="destructive">
          {t(c.unprocessed_webhooks, { count: health.unprocessed_webhooks })}
        </Badge>
      ) : (
        <span>{t(c.unprocessed_webhooks, { count: 0 })}</span>
      )}
      <span>{reconcile}</span>
    </section>
  );
}
