/**
 * Wire types for the pagebuilder JSON admin API.
 *
 * These mirror the Pydantic DTOs in `pagebuilder.contracts.schemas`. Keep
 * the two in sync when either changes.
 */

export type PageStatus = 'draft' | 'submitted_for_review' | 'published';

export type RevisionEvent = 'publish' | 'unpublish' | 'submit' | 'approve' | 'reject';

export interface PageRead {
  id: number;
  slug: string;
  title: string;
  status: PageStatus;
  has_published: boolean;
  /** Title for search results and link previews. Null means "use the title". */
  meta_title: string | null;
  meta_description: string | null;
  og_image: string | null;
  canonical_url: string | null;
  index_in_search: boolean;
  rejection_note: string | null;
  publish_at: string | null;
  unpublish_at: string | null;
  /** Breadcrumb parent. Deliberately does not affect the public URL. */
  parent_id: number | null;
  /** Offered as a starting point in the New page dialog. */
  is_template: boolean;
  /** Membership of the site nav. The *order* belongs to the layout editor. */
  show_in_header_nav: boolean;
  show_in_footer: boolean;
  /** When the page was moved to trash; null while it is live. */
  deleted_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface PageDetail extends PageRead {
  draft_data: Record<string, unknown>;
  published_data: Record<string, unknown> | null;
  json_ld: Record<string, unknown> | null;
}

export interface LayoutDetail {
  id: number;
  header_data: Record<string, unknown>;
  footer_data: Record<string, unknown>;
  created_at: string;
  updated_at: string | null;
}

export interface LayoutRevisionRead {
  id: number;
  layout_id: number;
  note: string | null;
  created_at: string;
  created_by: string | null;
}

export interface LayoutUpdate {
  header_data?: Record<string, unknown> | null;
  footer_data?: Record<string, unknown> | null;
  note?: string | null;
}

export interface PageRevisionRead {
  id: number;
  page_id: number;
  title: string;
  meta_description: string | null;
  og_image: string | null;
  event: RevisionEvent;
  note: string | null;
  created_at: string;
  created_by: string | null;
}

export interface MediaAssetVariant {
  filename: string;
  url: string;
  content_type: string;
  width: number;
  height: number | null;
  size_bytes: number;
}

export interface MediaUsage {
  page_id: number;
  title: string;
  slug: string;
  status: string;
  /** True when only the draft references it — the live page does not. */
  draft_only: boolean;
}

export interface MediaAssetDetail {
  asset: MediaAssetRead;
  used_in: MediaUsage[];
  used_in_total: number;
}

export interface MediaAssetRead {
  id: number;
  filename: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  url: string;
  width: number | null;
  height: number | null;
  folder: string | null;
  alt_text: string;
  caption: string;
  credit: string;
  variants: Record<string, MediaAssetVariant>;
  created_at: string;
}

export interface MediaListResponse {
  items: MediaAssetRead[];
  next_cursor: number | null;
  folders: string[];
  /** Only present when the request used offset paging. */
  total?: number | null;
}

export interface MediaListQuery {
  search?: string;
  content_type?: string;
  /**
   * Folder filter. Omit for "any folder", pass an empty string for
   * "Unfiled" (rows where folder IS NULL), or pass a path like
   * "marketing/heros" to match an exact folder.
   */
  folder?: string;
  min_size_bytes?: number;
  max_size_bytes?: number;
  cursor?: number;
  /** Offset paging, used by the image-picker gallery. Makes the response
   *  carry `total`; takes precedence over `cursor`. */
  offset?: number;
  limit?: number;
}

export interface PageWritePayload {
  title?: string;
  slug?: string;
  meta_description?: string | null;
  og_image?: string | null;
  canonical_url?: string | null;
  index_in_search?: boolean;
  json_ld?: Record<string, unknown> | null;
  draft_data?: Record<string, unknown>;
  publish_at?: string | null;
  unpublish_at?: string | null;
  parent_id?: number | null;
  is_template?: boolean;
  meta_title?: string | null;
  show_in_header_nav?: boolean;
  show_in_footer?: boolean;
  /** Seed `draft_data` from an existing page — the New page dialog's
   *  templates and its "copy a page" are the same operation. Write-only. */
  copy_from_page_id?: number | null;
}

/**
 * Body for ``POST /pages/{id}/schedule``.
 *
 * A field's *presence* tells the server "act on me" — omit a field to
 * leave the stored value alone, send ``null`` to clear it, send an ISO
 * timestamp to set it. So ``{publish_at: "2026-…"}`` schedules a publish
 * without touching ``unpublish_at``.
 */
export interface ScheduleRequest {
  publish_at?: string | null;
  unpublish_at?: string | null;
}

export interface BlockChange {
  id: string;
  type?: string;
  fields: string[];
  type_before?: string;
}

export interface MetadataChange {
  before: unknown;
  after: unknown;
}

export interface RevisionDiff {
  before_id: number;
  after_id: number;
  metadata: Record<string, MetadataChange>;
  blocks: {
    added: BlockChange[];
    removed: BlockChange[];
    changed: BlockChange[];
  };
}

export interface UploadMediaOptions {
  folder?: string | null;
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
}
