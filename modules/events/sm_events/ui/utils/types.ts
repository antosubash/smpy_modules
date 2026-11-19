export const VISIBILITIES = ['private', 'internal', 'public'] as const;
export type Visibility = (typeof VISIBILITIES)[number];
export const DEFAULT_COLOR = '#2563eb';
export type CalendarSource = {
  id: string;
  settings: Record<string, unknown>;
  installed: boolean;
  label_key: string | null;
  /** What is wrong with the stored settings that this reader may be told. */
  problems?: { loc: (string | number)[]; code: string; message: string }[];
};
export type Calendar = {
  id: string;
  slug: string;
  name: string;
  color: string;
  description: string | null;
  visibility: Visibility;
  owner_id: string;
  owner_name: string | null;
  default_timezone: string;
  /** Reminder lead times this calendar suggests (minutes); `null`: the site's. */
  default_reminder_minutes: number[] | null;
  /** The plugin sources enabled here; `settings` is empty unless the caller can manage them. */
  sources: CalendarSource[];
  /** What a write to the sources sends back (empty for one who cannot manage them). */
  sources_version: string;
  created_at: string;
  updated_at: string | null;
  deleted_at: string | null;
  can_edit: boolean;
  can_own: boolean;
  can_write_events: boolean;
  can_publish: boolean;
};
export type CalendarInput = {
  name: string;
  slug?: string;
  color: string;
  description: string | null;
  default_timezone: string;
  /** `null` goes back to the site's suggestion; omitted leaves it as it is. */
  default_reminder_minutes?: number[] | null;
  visibility?: Visibility;
};
export type ShareRole = 'view' | 'edit';
export type Share = {
  id: string;
  subject_id: string;
  subject_label?: string | null;
  role: string;
  expired: boolean;
};
export type ShareCandidate = { id: string; display_name: string; email: string };

export type Category = {
  id: string;
  slug: string;
  names: Record<string, string>;
  color: string | null;
};
export type CategoryInput = { slug?: string; names: Record<string, string>; color: string | null };
