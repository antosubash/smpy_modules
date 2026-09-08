/**
 * Wire types for the news JSON API.
 *
 * These mirror the Pydantic DTOs in `news.contracts.schemas`. Keep the two in
 * sync when either changes.
 *
 * Split out of `api.ts` rather than declared beside the calls, the same way
 * pagebuilder splits `mediaApi.ts` from its `types.ts`: the shapes are read by
 * screens that never make a request, and `api.ts` re-exports them so nothing
 * had to change its import.
 */

/** Workflow state of an article.
 *
 * News' own, on news' own column. The values are unchanged from when they were
 * a pagebuilder page's status mapped across a module boundary, so a client
 * written against the old wire format still reads them.
 */
export type ArticleStatus = 'draft' | 'submitted_for_review' | 'published';

export interface ArticleRead {
  id: number;
  slug: string;
  title: string;
  excerpt: string;
  cover_image_url: string;
  category: string;
  tags: string[];
  /** Held at the top of /news and of every feed block. */
  pinned: boolean;
  /** Whether feed blocks may list it. Does not affect the admin list. */
  show_in_feed: boolean;
  author: string;
  published_at: string | null;
  /** Which language the article is written in. Fixed for its lifetime: slugs
   *  are unique per `(locale, slug)`, so this is half of what identifies the
   *  public address. */
  locale: string;
  /** What this article shares with its counterparts in other languages. Lets
   *  the editor list them without a query per row.
   *
   *  Always present — an article that has never been translated is a group of
   *  one, the same way a pagebuilder page is. The degenerate value is `""`,
   *  not null, so a caller must test it for emptiness rather than for
   *  presence: passing `""` to a `translation_group` filter drops the filter
   *  instead of narrowing it. */
  translation_group: string;
  /** Workflow state. Always `published` for anyone without `news.edit` —
   *  drafts are filtered out server-side. */
  status: ArticleStatus;
  url: string;
  /** Where the body is composed. Sent by the server rather than assembled
   *  here, so this list holds no opinion about how the module routes its own
   *  screens. */
  edit_url: string;
}

/** One article, with the fields only its editor screens need.
 *
 * Extends the listing shape rather than replacing it, so a component holding
 * an `ArticleRead` can be handed one of these without branching.
 */
export interface ArticleDetail extends ArticleRead {
  /** The block document the canvas edits. Never what readers are served —
   *  that is the snapshot taken at publish. */
  draft_data: Record<string, unknown>;
  /** Whether a published snapshot exists. Distinct from `status`: an
   *  unpublished article can still have one, from before it was taken down. */
  has_published: boolean;
  meta_description: string;
  og_image: string;
  canonical_url: string;
  index_in_search: boolean;
  json_ld: Record<string, unknown> | null;
  rejection_note: string | null;
  /** When the article goes live and comes down by itself.
   *
   * On this shape rather than `ArticleRead`, and deliberately: a published
   * article can carry a future `unpublish_at`, and the listing DTO is what
   * anonymous readers are served. */
  publish_at: string | null;
  unpublish_at: string | null;
}

export interface RevisionRead {
  id: number;
  article_id: number;
  title: string;
  event: 'publish' | 'unpublish' | 'submit' | 'approve' | 'reject';
  note: string | null;
  created_at: string | null;
  created_by: string | null;
}

export interface ArticleCounts {
  all: number;
  draft: number;
  published: number;
  undated: number;
}

export interface ArticleListResponse {
  items: ArticleRead[];
  /** Matched the whole filter, status included — what the pager counts. */
  total: number;
  /** What each status pill would show. `undated` overlaps draft and
   *  published, so these deliberately do not sum to `all`. */
  counts: ArticleCounts;
}

export interface CategoryCount {
  category: string;
  count: number;
}

export interface CategoryListResponse {
  items: CategoryCount[];
}

export interface ArticleTranslationPayload {
  locale: string;
  /** Defaults to the source article's slug, which is free unless an unrelated
   *  article in that language already took it. */
  slug?: string;
  /** Defaults to the source's headline, i.e. untranslated. */
  title?: string;
}
