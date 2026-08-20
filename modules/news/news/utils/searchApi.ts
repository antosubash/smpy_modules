/** Client for the cross-section admin search. */

import { read } from './http';

export interface SearchHit {
  id: number;
  title: string;
  /** Pre-rendered by the server: which fields it names depends on the section,
   *  so the screen does not have to branch on type to render a result. */
  subtitle: string;
  url: string;
  excerpt: string;
}

export interface SearchResults {
  query: string;
  articles: SearchHit[];
  pages: SearchHit[];
  media: SearchHit[];
  article_total: number;
  page_total: number;
  media_total: number;
  /** Where each section's "see all" goes. Sent by the server: both land in
   *  pagebuilder, and how that module routes its own screens is not something
   *  this one should be spelling out here. */
  pages_more_url: string;
  media_more_url: string;
}

export const searchEverything = (q: string, signal?: AbortSignal) =>
  read<SearchResults>(`/search?q=${encodeURIComponent(q)}`, signal);
