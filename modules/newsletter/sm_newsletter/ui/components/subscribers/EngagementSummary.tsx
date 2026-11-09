/** Four aggregates (G15): campaigns sent, the last send, opened and clicked campaigns.
 *  No per-send list. Opens carry PR 5's "approximate" caption. */

import { keys, useT } from '../../utils/i18n';
import type { Engagement } from '../../utils/types';

export function EngagementSummary({ engagement }: { engagement: Engagement }) {
  const { t, locale } = useT();
  const copy = keys.newsletter.subscribers.detail;
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium' });
  const last = engagement.last_sent_at
    ? `${date.format(new Date(engagement.last_sent_at))}${
        engagement.last_campaign_name ? `, ${engagement.last_campaign_name}` : ''
      }`
    : t(copy.never_sent);
  return (
    <dl className="grid grid-cols-2 gap-3 text-sm">
      <div>
        <dt className="text-muted-foreground">{t(copy.campaigns_sent)}</dt>
        <dd className="font-medium">{engagement.campaigns_sent}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">{t(copy.last_sent)}</dt>
        <dd className="font-medium">{last}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">{t(copy.opened)}</dt>
        <dd className="font-medium">{engagement.opened_campaigns}</dd>
        <dd className="text-xs text-muted-foreground">{t(keys.newsletter.report.approx.opens)}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">{t(copy.clicked)}</dt>
        <dd className="font-medium">{engagement.clicked_campaigns}</dd>
      </div>
    </dl>
  );
}
