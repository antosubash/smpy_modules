import { describe, expect, it } from 'vitest';

import { archiveUrl } from './archiveUrl';

/** The pager's addresses, pinned as literal strings.
 *
 * Deliberately not asserted by parsing the result back out: the point is that
 * these exact spellings match what `archive_url` in
 * `news/endpoints/public/_archive.py` writes into the canonical link, and a
 * test that normalised the URL first would pass while the two drifted. The
 * Python side's equivalent assertion is in
 * `test_public_search.py::test_the_canonical_names_the_search`.
 */
describe('archiveUrl — matching news/endpoints/public/_archive.py', () => {
  it('leaves page 1 without a query string', () => {
    // `/news/` and `/news/?page=1` being two addresses for one page is how an
    // archive ends up competing with itself in an index.
    expect(archiveUrl('/news/', 1, '')).toBe('/news/');
  });

  it('numbers every page past the first', () => {
    expect(archiveUrl('/news/', 2, '')).toBe('/news/?page=2');
  });

  it('carries the search term through the pager', () => {
    // Without this, paging a search silently drops it and page 2 of "canopy"
    // is page 2 of the whole archive.
    expect(archiveUrl('/news/', 2, 'canopy')).toBe('/news/?q=canopy&page=2');
  });

  it('puts q before page', () => {
    // One page of one search has to have exactly one spelling, or the
    // canonical link names a URL nothing links to.
    expect(archiveUrl('/news/', 3, 'a')).toBe('/news/?q=a&page=3');
  });

  it('drops page 1 but keeps the term', () => {
    expect(archiveUrl('/news/', 1, 'canopy')).toBe('/news/?q=canopy');
  });

  it('encodes a term the way the server does', () => {
    // `+` for a space and UTF-8 percent-encoding, which is what Python's
    // urlencode produces — the two have to agree character for character.
    expect(archiveUrl('/news/', 1, 'canopy loss')).toBe('/news/?q=canopy+loss');
    expect(archiveUrl('/news/', 1, 'é')).toBe('/news/?q=%C3%A9');
  });

  it('builds on whatever archive it was given', () => {
    // A search typed on a category page stays in that category.
    expect(archiveUrl('/de/news/category/haushalt', 2, 'x')).toBe(
      '/de/news/category/haushalt?q=x&page=2',
    );
  });
});
