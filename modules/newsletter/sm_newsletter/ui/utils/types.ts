/** Wire types of `/api/newsletter`, mirroring `sm_newsletter/web/schemas/*.py`. */

type BlockType =
  | 'Heading'
  | 'RichText'
  | 'Image'
  | 'Button'
  | 'Divider'
  | 'Spacer'
  | 'ArticleCard'
  | 'PageCard';

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
}

export interface CampaignDetail extends CampaignSummary {
  preheader: string;
  from_name: string | null;
  reply_to: string | null;
  audience: string;
  body: Block[];
  scheduled_at: string | null;
  started_at: string | null;
  finished_at: string | null;
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
  | 'https_required';

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
  recipients: number;
  estimated_finish: string;
  overlaps: boolean;
  daily_rate: number;
}

export interface CampaignPage {
  items: CampaignSummary[];
  total: number;
}

export type CardKind = 'article' | 'page';

export interface CardHit {
  kind: CardKind;
  source_id: number;
  title: string;
  excerpt: string;
  image_url: string;
  url: string;
  locale: string;
}

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

export interface Preview {
  subject: string;
  html: string;
  text: string;
  warnings: string[];
}

export interface TestSendResult {
  recipient: string;
  outcome: string;
  code: number | null;
  detail: string;
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
}

export type SettingsUpdate = Partial<Omit<SettingsOut, 'has_password'>>;
export type SettingsSaved = SettingsOut & { password_cleared: boolean };
