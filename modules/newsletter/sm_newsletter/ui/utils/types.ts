/** Wire types of `/api/newsletter`, mirroring `sm_newsletter/web/schemas/*.py`. */

type BlockType =
  | 'Heading'
  | 'RichText'
  | 'Image'
  | 'Button'
  | 'Divider'
  | 'Spacer'
  | 'ArticleCard'
  | 'PageCard'
  | 'EventCard';

export type Block = { type: BlockType; props: Record<string, unknown> & { id: string } };

export interface CampaignSummary {
  id: number;
  name: string;
  subject: string;
  status: string;
  list_type_key: string;
  revision: number;
  updated_at: string | null;
  recipient_count: number;
  sent_count: number;
  started_at: string | null;
  finished_at: string | null;
}

/** A list row: unique opens and clicks of `sent` rows (B5); the detail has no such field. */
export interface CampaignListItem extends CampaignSummary {
  opens_unique_accepted: number;
  clicks_unique_accepted: number;
}

export interface CampaignDetail extends CampaignSummary {
  preheader: string;
  from_name: string | null;
  reply_to: string | null;
  audience: string;
  body: Block[];
  scheduled_at: string | null;
  paused_code: PausedCode | null;
  paused_detail: string | null;
  failed_count: number;
  bounced_count: number;
  suppressed_count: number;
  unsubscribe_count: number;
}

export type PausedCode =
  | 'manual'
  | 'smtp_rejected'
  | 'smtp_auth'
  | 'list_unavailable'
  | 'https_required'
  | 'audience_unavailable';

/** `GET /campaigns/{id}/progress`. */
export interface Progress {
  status: string;
  recipients: number;
  queued: number;
  sending: number;
  sent: number;
  failed: number;
  bounced: number;
  suppressed: number;
  skipped: number;
  cancelled: number;
  paused_code: PausedCode | null;
  paused_detail: string | null;
  scheduled_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  estimated_finish: string | null;
  daily_rate: number;
}

/** `GET /campaigns/{id}/estimate`. */
export interface Estimate {
  /** Null: a tag or segment audience and a caller without `records.view`. */
  recipients: number | null;
  estimated_finish: string;
  overlaps: boolean;
  daily_rate: number;
}

export interface LinkStat {
  position: number;
  url: string;
  unique: number;
  total: number;
}

export interface ReportPoint {
  at: string;
  opens: number;
  clicks: number;
}

/** `GET /campaigns/{id}/report`: raw counts, rates are computed in the UI (T14). */
export interface Report {
  campaign_id: number;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  recipients: number;
  sent: number;
  failed: number;
  bounced: number;
  suppressed: number;
  skipped: number;
  unsubscribed: number;
  opens_unique: number;
  opens_total: number;
  clicks_unique: number;
  clicks_total: number;
  opens_unique_accepted: number;
  clicks_unique_accepted: number;
  tracking_opens: boolean;
  tracking_clicks: boolean;
  links: LinkStat[];
  bucket: 'hour' | 'day';
  timeline: ReportPoint[];
}

export interface CampaignPage {
  items: CampaignListItem[];
  total: number;
}

export type CardKind = 'article' | 'page' | 'event';

export interface ArticleCardHit {
  kind: 'article' | 'page';
  source_id: number;
  title: string;
  excerpt: string;
  image_url: string;
  url: string;
  locale: string;
}

/** An upcoming event the public could see. `source_id` is its id (never shown). */
export interface EventCardHit {
  kind: 'event';
  source_id: string;
  title: string;
  excerpt: string;
  image_url: string;
  url: string;
  ics_url: string;
  locale: string;
  starts_at: string;
  ends_at: string;
  all_day: boolean;
  start_date: string | null;
  end_date: string | null;
  timezone: string;
  attendance_mode: 'in_person' | 'online' | 'hybrid';
  place: string;
  cancelled: boolean;
  /** The date and time as the email words them: the server's own, zone abbreviation included. */
  when: string;
}

export type CardHit = ArticleCardHit | EventCardHit;

export interface MediaHit {
  id: number;
  filename: string;
  url: string;
}

/** A card block's props, ready to drop into the body. */
export interface CardSnapshot {
  id: string;
  source_id: number;
  title: string;
  excerpt: string;
  image_url: string;
  url: string;
  locale: string;
  snapshot_at: string;
}

/** An event card block's props, ready to drop into the body. */
export type EventCardSnapshot = Omit<EventCardHit, 'kind' | 'when'> & {
  id: string;
  snapshot_at: string;
};

export interface Preview {
  subject: string;
  html: string;
  text: string;
  warnings: string[];
}

/** One recipient's answer. `outcome` is `accepted`, `rejected`, `unknown`,
 *  `failed`, `recipient_not_allowed` or `suppressed`; `code` is `smtp_<reply>`,
 *  `dispatch_busy` or null. The relay's reply text is never sent (#348). */
export interface TestSendResult {
  recipient: string;
  outcome: string;
  code: string | null;
}

export interface SettingsOut {
  transport: 'smtp' | 'console';
  smtp_host: string;
  smtp_port: number;
  smtp_security: 'starttls' | 'tls';
  smtp_username: string;
  has_password: boolean;
  from_address: string;
  from_name: string;
  reply_to: string;
  daily_limit: number;
  per_minute_limit: number;
  tracking_opens: boolean;
  tracking_clicks: boolean;
  physical_address: string;
  test_send_extra_recipients: string[];
}

export type SettingsUpdate = Partial<Omit<SettingsOut, 'has_password'>>;
export type SettingsSaved = SettingsOut & { password_cleared: boolean };

export * from './subscriberTypes';
