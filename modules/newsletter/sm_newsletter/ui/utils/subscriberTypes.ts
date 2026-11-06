/** Wire types of segments, subscribers and suppressions (PR 6), mirroring `web/schemas/{segments,subscribers,suppressions}.py`. */

export type RuleOp =
  | 'is'
  | 'is_not'
  | 'any'
  | 'all'
  | 'none'
  | 'contains'
  | 'starts_with'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'before'
  | 'since';

export interface FieldChoice {
  value: string;
  label: string;
}

/** `GET /lists/{key}/fields`: what a segment rule may name, and the ops each accepts. */
export interface ListField {
  key: string;
  label: string;
  type: string;
  many: boolean;
  choices: FieldChoice[];
  system: boolean;
  ops: RuleOp[];
}

export interface Rule {
  field: string;
  op: RuleOp;
  value: string | string[];
}

export interface Segment {
  id: number;
  name: string;
  list_type_key: string;
  rules: Rule[];
  updated_at: string | null;
}

export interface SegmentBody {
  name: string;
  list_type_key: string;
  rules: Rule[];
}

export type SubscriberStatus = 'pending' | 'confirmed' | 'unsubscribed';

export interface Subscriber {
  uuid: string;
  email: string;
  status: SubscriberStatus;
  first_name: string | null;
  last_name: string | null;
  tags: string[];
  confirmed_at: string | null;
  trashed: boolean;
  suppressed: boolean;
}

export interface SubscriberPage {
  items: Subscriber[];
  total: number;
  counts: Record<SubscriberStatus, number>;
  records_url: string;
}

/** The body of `POST /lists/{key}/subscribers/search`; the text only ever travels here (C5). */
export interface SubscriberSearch {
  status?: SubscriberStatus | null;
  q?: string | null;
  tag?: string | null;
  segment?: number | null;
  offset?: number;
  limit?: number;
}

export interface Engagement {
  campaigns_sent: number;
  last_sent_at: string | null;
  last_campaign_name: string | null;
  opened_campaigns: number;
  clicked_campaigns: number;
}

export type SuppressionReason = 'hard_bounce' | 'complaint' | 'imported_cleaned' | 'unsubscribed';

export interface Suppression {
  id: number;
  fingerprint: string;
  reason: SuppressionReason;
  list_type_key: string;
  source: string;
  created_at: string;
  version: string;
  liftable: boolean;
  /** Detail only: `null` when liftable now. */
  block?: string | null;
}

export interface SubscriberDetail {
  subscriber: Subscriber;
  engagement: Engagement;
  suppressions: Suppression[];
  records_url: string;
}

export interface SuppressionPage {
  items: Suppression[];
  total: number;
  counts: Partial<Record<SuppressionReason, number>>;
}

export interface Lift {
  id: number;
  fingerprint: string;
  reason: SuppressionReason;
  list_type_key: string;
  source: string;
  suppressed_at: string;
  lifted_at: string;
  lifted_by: string | null;
  note: string;
}

export interface LiftPage {
  items: Lift[];
  total: number;
}
