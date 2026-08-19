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
}

export const searchEverything = (q: string, signal?: AbortSignal) =>
  read<SearchResults>(`/search?q=${encodeURIComponent(q)}`, signal);
