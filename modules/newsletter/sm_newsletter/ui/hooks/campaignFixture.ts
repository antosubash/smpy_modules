/** Test support: a draft `CampaignDetail` for the editor hook tests, at a given revision. */

import type { Block, CampaignDetail } from '../utils/types';

export function campaign(revision: number, body: Block[] = []): CampaignDetail {
  return {
    id: 7,
    name: 'Spring',
    subject: 'Hello',
    status: 'draft',
    list_type_key: 'news',
    revision,
    updated_at: null,
    recipient_count: 0,
    sent_count: 0,
    preheader: '',
    from_name: null,
    reply_to: null,
    audience: 'all',
    scheduled_at: null,
    started_at: null,
    finished_at: null,
    paused_code: null,
    paused_detail: null,
    failed_count: 0,
    bounced_count: 0,
    suppressed_count: 0,
    unsubscribe_count: 0,
    body,
  };
}
