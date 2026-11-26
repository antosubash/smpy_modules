import { PublicHead, type PublicHeadValues } from './PublicHead';

/** Metadata for stock pages and host replacements; legacy props remain public API. */
export interface ArticleHeadProps {
  /** Pass the endpoint's head prop unchanged to preserve server/client parity. */
  head?: PublicHeadValues;
  title: string;
  meta_description: string | null;
  og_image: string | null;
  canonical_url?: string | null;
  og_url?: string | null;
  index_in_search?: boolean;
  json_ld?: Record<string, unknown> | null;
  site_name?: string | null;
  twitter_handle?: string | null;
  category?: string;
  author?: string;
  published_at?: string | null;
}

export function ArticleHead({
  head,
  title,
  meta_description,
  og_image,
  canonical_url,
  og_url,
  index_in_search = true,
  json_ld,
  site_name,
  twitter_handle,
  category,
  author,
  published_at,
}: ArticleHeadProps) {
  return (
    <PublicHead
      article
      head={
        head ?? {
          title,
          description: meta_description,
          image: og_image,
          canonical: canonical_url,
          og_url: og_url ?? null,
          index_in_search,
          json_ld,
          site_name,
          twitter_handle,
          section: category,
          author,
          published_at,
        }
      }
    />
  );
}
