import type { Report } from '../../utils/types';

/** A started campaign's report: 200 accepted, 50 unique opens of them. */
export function report(over: Partial<Report> = {}): Report {
  return {
    campaign_id: 7,
    status: 'sent',
    started_at: '2026-11-01T10:00:00Z',
    finished_at: '2026-11-01T11:00:00Z',
    recipients: 250,
    sent: 200,
    failed: 10,
    bounced: 5,
    suppressed: 20,
    skipped: 15,
    unsubscribed: 3,
    opens_unique: 60,
    opens_total: 90,
    clicks_unique: 12,
    clicks_total: 20,
    opens_unique_accepted: 50,
    clicks_unique_accepted: 10,
    tracking_opens: true,
    tracking_clicks: true,
    links: [],
    bucket: 'hour',
    timeline: [],
    ...over,
  };
}
