import type { SourceStatus } from '../extensions/types';

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
  /** False when no plugin on this server provides the type: its `extra` is kept, read-only. */
  type_installed?: boolean;
  type_label_key?: string | null;
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
export type RegistrationCount = {
  occurrence_key: string;
  /** `null`: the date no longer exists on the calendar but still holds seats. */
  start: string | null;
  start_local: string | null;
  taken: number;
  capacity: number | null;
};
export type RegistrationMode = 'none' | 'external' | 'builtin';
/** An event's registration settings as the API returns them. */
export type RegistrationOut = {
  mode: RegistrationMode;
  url: string | null;
  provider: string | null;
  target: string | null;
  capacity: number | null;
  opens_at_local: string | null;
  closes_at_local: string | null;
  show_seats: boolean;
  reminder_minutes: number | null;
  /** The editor may edit the event but not read the form: provider and target are withheld. */
  target_hidden: boolean;
  /** `false`: this host has no such provider; the settings are kept and cannot be changed. */
  provider_installed: boolean | null;
};
/** What the API takes: a full replacement of the event's settings. */
export type RegistrationIn = {
  mode: RegistrationMode;
  url?: string | null;
  provider?: string | null;
  target?: string | null;
  capacity?: number | null;
  opens_at_local?: string | null;
  closes_at_local?: string | null;
  show_seats?: boolean;
  reminder_minutes?: number | null;
};
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
  registration: RegistrationOut;
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
  /** The whole registration settings; left out, the stored ones stay as they are. */
  registration?: RegistrationIn;
};
export type EventCreate = EventFields & {
  calendar_id: string;
  /** A registered type's id; the default type when left out. */
  type?: string;
  extra?: Record<string, unknown>;
  parent_id?: string | null;
  times: TimesInput;
  texts: Record<string, TextInput>;
};
export type EventPatch = Partial<EventFields> & {
  expected_revision: number;
  times?: TimesInput;
  texts?: Record<string, TextInput | null>;
  /** Replaces the whole `extra`; sent only when a section changed it. */
  extra?: Record<string, unknown>;
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
  origin_label?: string | null;
};
export type OccurrencePage = {
  items: Occurrence[];
  truncated: boolean;
  /** How each plugin source answered (a console read only; the public API omits it). */
  sources?: SourceStatus[];
};
export type OccurrenceQuery = {
  start: string;
  end: string;
  calendar?: string[];
  category?: string[];
  type?: string[];
  source?: string[];
  locale?: string;
  include_unpublished?: boolean;
};
