/** What the server renders the public screens from (`web/schemas/public*.py`). Every URL is a
 *  path; only `canonical_url` and the `alternates` are absolute. */
import type { Node } from './richtext-types';

export type CalendarRef = { slug: string; name: string; color: string };
export type CategoryRef = { slug: string; name: string; color: string | null };

export type PublicListItem = {
  key: string;
  url: string;
  title: string;
  lang: string;
  all_day: boolean;
  /** `YYYY-MM-DDTHH:MM` on the event's own clock. */
  start_local: string;
  end_local: string;
  start_date: string | null;
  /** The last day, inclusive. */
  end_date: string | null;
  timezone: string;
  show_timezone: boolean;
  status: 'confirmed' | 'cancelled';
  rescheduled: boolean;
  calendar: CalendarRef;
  category: CategoryRef | null;
  venue_name: string | null;
  attendance_mode: string;
  summary: string | null;
};

export type MonthGroup = { month: string; items: PublicListItem[] };
export type PublicCalendar = {
  id: string;
  slug: string;
  name: string;
  color: string;
  description: string | null;
  default_timezone: string;
  url: string;
  feed_url: string;
};
export type PublicCategory = { id: string; slug: string; name: string; color: string | null };
export type Alternate = { locale: string; url: string };

export type PublicIndexProps = {
  locale: string;
  /** The calendar's name, or what the site calls its events. */
  title: string;
  page: number;
  page_count: number;
  groups: MonthGroup[];
  calendars: PublicCalendar[];
  calendar: PublicCalendar | null;
  categories: PublicCategory[];
  category: string | null;
  view: 'list' | 'calendar';
  feed_url: string;
  default_timezone: string;
  api_url: string;
  alternates: Alternate[];
};

export type Status = 'scheduled' | 'cancelled' | 'rescheduled';
export type When = {
  start: string;
  end: string;
  all_day: boolean;
  start_local: string;
  end_local: string;
  start_date: string | null;
  /** Exclusive. */
  end_date: string | null;
  status: Status;
  previous_start_local: string | null;
  date_param: string | null;
};
export type NextOccurrence = {
  date_param: string | null;
  url: string;
  start_local: string;
  end_local: string;
  status: Status;
};
export type Place = {
  mode: string;
  venue_name: string | null;
  address: string | null;
  online_url: string | null;
  latitude: number | null;
  longitude: number | null;
};

export type PublicEventProps = {
  locale: string;
  title: string;
  summary: string | null;
  description_tree: Node[];
  timezone: string;
  all_day: boolean;
  when: When | null;
  series: { rule: string; start_local: string; next: NextOccurrence[] } | null;
  cancelled: boolean;
  place: Place;
  organiser: string | null;
  image: string | null;
  category: CategoryRef | null;
  calendar: CalendarRef & { url: string };
  parent: { title: string; url: string } | null;
  sub_events: PublicListItem[];
  registration_url: string | null;
  ics_url: string;
  canonical_url: string;
  alternates: Alternate[];
  json_ld: unknown;
  index_in_search: boolean;
};

export type PublicNotFoundProps = {
  locale: string;
  index_url: string;
  suggestions: PublicListItem[];
};
