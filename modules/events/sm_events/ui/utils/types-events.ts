/** The events API's shapes, as `sm_events/web/schemas/events_*.py` returns them. */

export const EVENT_STATUSES = ['draft', 'in_review', 'published'] as const;
export type EventStatus = (typeof EVENT_STATUSES)[number];
/** `scheduled` is a filter, not a status: a draft or in-review event with `publish_at`. */
export type ListStatus = EventStatus | 'scheduled';
export const ATTENDANCE_MODES = ['in_person', 'online', 'hybrid'] as const;
export type AttendanceMode = (typeof ATTENDANCE_MODES)[number];
export type OverrideKind = 'skipped' | 'cancelled' | 'moved';

export type EventBase = {
  id: string;
  calendar_id: string;
  parent_id: string | null;
  type: string;
  status: EventStatus;
  scheduled: boolean;
  cancelled: boolean;
  all_day: boolean;
  timezone: string;
  starts_at: string;
  ends_at: string;
  /** The event's own wall clock: `YYYY-MM-DDTHH:MM`, or `YYYY-MM-DD` (inclusive end) all day. */
  start_local: string;
  end_local: string;
  rrule: string | null;
  category_id: string | null;
  venue_name: string | null;
  revision: number;
  publish_at: string | null;
  published_at: string | null;
  trashed: boolean;
  can_write: boolean;
  can_publish: boolean;
  locked: boolean;
};
export type EventListItem = EventBase & { title: string; lang: string };
export type EventPage = { items: EventListItem[]; total: number; page: number; page_size: number };

export type EventText = {
  slug: string;
  title: string;
  summary: string | null;
  description: string;
  seo_title: string | null;
  seo_description: string | null;
  noindex: boolean;
};
export type TextInput = {
  title: string;
  slug: string | null;
  summary: string | null;
  description: string;
  seo_title: string | null;
  seo_description: string | null;
  noindex: boolean;
};
export type Override = {
  id: number;
  original_start: string;
  kind: OverrideKind;
  starts_at: string | null;
  ends_at: string | null;
  start_local: string | null;
  end_local: string | null;
  note: string | null;
};
export type SubEvent = { id: string; title: string; start_local: string };
export type EventDetail = EventBase & {
  uid: string;
  recurrence_until: string | null;
  publish_at_local: string | null;
  attendance_mode: AttendanceMode;
  address: string | null;
  online_url: string | null;
  latitude: number | null;
  longitude: number | null;
  organiser: string | null;
  image: string | null;
  registration_url: string | null;
  extra: Record<string, unknown>;
  created_at: string;
  updated_at: string | null;
  texts: Record<string, EventText>;
  overrides: Override[];
  sub_events: SubEvent[];
};

export type TimesInput = { all_day: boolean; timezone: string; start: string; end: string };
/** The writable columns a create and an update share. */
export type EventFields = {
  rrule: string | null;
  cancelled: boolean;
  attendance_mode: AttendanceMode;
  venue_name: string | null;
  address: string | null;
  online_url: string | null;
  latitude: number | null;
  longitude: number | null;
  category_id: string | null;
  organiser: string | null;
  image: string | null;
  registration_url: string | null;
};
export type EventCreate = EventFields & {
  calendar_id: string;
  parent_id?: string | null;
  times: TimesInput;
  texts: Record<string, TextInput>;
};
export type EventPatch = Partial<EventFields> & {
  expected_revision: number;
  times?: TimesInput;
  texts?: Record<string, TextInput | null>;
  drop_orphaned_overrides?: boolean;
};

export type WorkflowAction =
  | 'submit'
  | 'withdraw'
  | 'approve'
  | 'reject'
  | 'unschedule'
  | 'unpublish';
export type WorkflowBody = { expected_revision: number; publish_at_local?: string; note?: string };

export type Revision = {
  number: number;
  action: string;
  actor: string | null;
  /** The member's display name; `null` for a non-member, an address label or the beat. */
  actor_name: string | null;
  /** No actor at all (the beat), as opposed to an actor whose name is unknown. */
  system: boolean;
  /** The actor is the signed-in caller; shown as "You" even without a display name. */
  is_self: boolean;
  created_at: string;
  note: string | null;
};
export type RevisionDetail = Revision & { snapshot: Record<string, unknown> };

export type OverrideInput = {
  expected_revision: number;
  original_start: string;
  kind: OverrideKind;
  start?: string;
  end?: string;
  note?: string | null;
};
export type OverrideResult = Override & { event_revision: number };

export type PreviewInput = {
  times: TimesInput;
  rrule: string | null;
  event_id?: string;
  calendar_id?: string;
  after?: string;
  count?: number;
};
export type PreviewOccurrence = {
  start: string;
  end: string;
  start_local: string;
  end_local: string;
};
export type Preview = {
  occurrences: PreviewOccurrence[];
  recurrence_until: string | null;
  orphaned: Override[];
};

export type EventQuery = {
  calendar?: string;
  status?: ListStatus;
  category?: string;
  from?: string;
  to?: string;
  q?: string;
  trashed?: boolean;
  locale?: string;
  page?: number;
  page_size?: number;
};
export type Occurrence = {
  source: string;
  key: string;
  calendar_id: string;
  start: string;
  end: string;
  all_day: boolean;
  timezone: string;
  start_date: string | null;
  end_date: string | null;
  title: string;
  lang: string;
  color: string;
  url: string | null;
  status: 'confirmed' | 'cancelled';
  type: string;
  editable: boolean;
  event_id: string | null;
  original_start: string | null;
  event_status: string | null;
};
export type OccurrencePage = { items: Occurrence[]; truncated: boolean };
export type OccurrenceQuery = {
  start: string;
  end: string;
  calendar?: string[];
  category?: string[];
  type?: string[];
  locale?: string;
  include_unpublished?: boolean;
};
