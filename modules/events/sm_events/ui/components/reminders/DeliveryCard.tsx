/** The managers' Delivery card: whether reminders can go out, why not in words, and counts of
 *  the last 30 days: never who was or was not reminded. */
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { useEffect, useState } from 'react';
import { leadsSummary } from '../../reminders/leadText';
import { errorText } from '../../utils/api';
import { type Delivery, deliveryStatus } from '../../utils/api-reminders';
import { keys, useT } from '../../utils/i18n';

const REASONS: Record<string, string> = {
  disabled: keys.events.reminders.delivery.reason_disabled,
  no_public_base_url: keys.events.reminders.delivery.reason_no_public_base_url,
  no_mail_transport: keys.events.reminders.delivery.reason_no_mail_transport,
  console_mail: keys.events.reminders.delivery.reason_console_mail,
  worker_access_unavailable: keys.events.reminders.delivery.reason_worker_access_unavailable,
};
const FAILED: Record<string, string> = {
  send_failed: keys.events.reminders.delivery.failed_code_send_failed,
  send_timeout: keys.events.reminders.delivery.failed_code_send_timeout,
};

export function DeliveryCard({ settingsUrl }: { settingsUrl: string }) {
  const { t } = useT();
  const copy = keys.events.reminders.delivery;
  const [data, setData] = useState<Delivery | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    deliveryStatus(controller.signal)
      .then(setData)
      .catch((e) => !controller.signal.aborted && setError(errorText(e)));
    return () => controller.abort();
  }, []);
  return (
    <Card data-testid="delivery-card">
      <CardHeader>
        <CardTitle>
          <h2>{t(copy.title)}</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {error ? (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        ) : null}
        {data ? (
          <>
            <p>{t(data.enabled ? copy.enabled : copy.disabled)}</p>
            <p role="status">
              {data.available
                ? t(copy.ok)
                : data.reason && REASONS[data.reason]
                  ? t(REASONS[data.reason])
                  : t(keys.events.reminders.control.unavailable)}
            </p>
            <p>{t(copy.defaults, { leads: leadsSummary(t, data.defaults) })}</p>
            <p>
              <a className="underline" href={settingsUrl}>
                {t(copy.settings)}
              </a>
            </p>
            <h3 className="pt-2 font-medium">{t(copy.counts_title, { days: data.window_days })}</h3>
            <ul>
              <li>{t(copy.sent, { count: data.counts.sent })}</li>
              {Object.entries(data.counts.failed).map(([code, count]) => (
                <li key={code}>{t(FAILED[code] ?? copy.failed, { count })}</li>
              ))}
              <li>{t(copy.unfinished, { count: data.counts.unfinished })}</li>
            </ul>
            <p className="text-muted-foreground">{t(copy.unfinished_note)}</p>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}
