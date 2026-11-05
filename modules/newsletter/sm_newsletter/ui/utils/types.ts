/** Wire types of `/api/newsletter`, mirroring `sm_newsletter/web/schemas/*.py`. */

export type BlockType =
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
