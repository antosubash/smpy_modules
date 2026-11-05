// Fixtures shared by the SendingPanel tests.
import type { CampaignDetail, Progress } from '../../utils/types';

export function campaign(over: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: 7,
    name: 'Spring',
    subject: 'Hello',
    status: 'sending',
    list_type_key: 'news',
    revision: 3,
    updated_at: null,
    recipient_count: 300,
    sent_count: 100,
    preheader: '',
    from_name: null,
    reply_to: null,
    audience: 'all',
    body: [],
    scheduled_at: null,
    started_at: null,
    finished_at: null,
    paused_code: null,
    paused_detail: null,
    failed_count: 0,
    bounced_count: 0,
    suppressed_count: 0,
    unsubscribe_count: 0,
    ...over,
  };
}

export function progress(over: Partial<Progress> = {}): Progress {
  return {
    status: 'sending',
    recipients: 300,
    queued: 190,
    sending: 10,
    sent: 100,
    failed: 0,
    bounced: 0,
    suppressed: 0,
    skipped: 0,
    cancelled: 0,
    paused_code: null,
    paused_detail: null,
    scheduled_at: null,
    started_at: null,
    finished_at: null,
    estimated_finish: '2026-12-01T10:00:00Z',
    daily_rate: 100,
    ...over,
  };
}
