export type Visibility = 'private' | 'internal' | 'public';
export type Calendar = {
  id: string;
  slug: string;
  name: string;
  color: string;
  description: string | null;
  visibility: Visibility;
  owner_id: string;
  default_timezone: string;
  sources: unknown[];
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
