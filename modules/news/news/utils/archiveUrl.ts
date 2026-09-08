/** One archive page's address.
 *
 * The mirror of `archive_url` in `news/endpoints/public/_archive.py`, and it
 * has to stay one: the server writes the canonical link and this builds the
 * pager, so if the two spell the same page differently every paged search
 * declares a canonical URL that nothing on the site links to.
 *
 * What has to agree is the *order* and the omissions — `q` before `page`, and
 * no `page` parameter at all on page 1, because `/news/` and `/news/?page=1`
 * being two addresses is how an archive competes with itself in an index.
 * `archiveUrl.test.ts` pins the exact strings both sides must produce.
 */
export function archiveUrl(basePath: string, page: number, query: string): string {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (page > 1) params.set('page', String(page));
  const search = params.toString();
  return search ? `${basePath}?${search}` : basePath;
}
