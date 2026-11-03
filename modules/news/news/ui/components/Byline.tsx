/** Who wrote it and when, under the headline.
 *
 * Its own component for one reason: the byline is a link *or* plain text, never
 * a link to nowhere. A byline with no ASCII to fold onto has no archive address
 * — see `news/authors.py` — and the server sends `url` as null for it. Rendering
 * an `<a>` with an empty or missing `href` there would give a reader something
 * that looks clickable and isn't, which is worse than the plain text this
 * replaced. Pulling it out of `PublicArticle` is what lets that be asserted
 * (`Byline.test.tsx`) rather than read.
 *
 * In `components/`, not `pages/`. Every file under a module's `pages` directory
 * is registered as an Inertia page by `import.meta.glob`.
 */

interface Props {
  author?: string;
  /** Already formatted for display — the date rule is `formatArticleDate`'s. */
  dated?: string | null;
  /** The byline's archive, or null when the byline has no address. */
  url?: string | null;
}

export function Byline({ author, dated, url }: Props) {
  // Nothing to say. An empty line of muted text under a headline reads as
  // something that failed to load.
  if (!author && !dated) return null;
  return (
    <p className="mt-3 text-sm text-muted-foreground">
      {author &&
        (url ? (
          <a href={url} className="hover:underline">
            {author}
          </a>
        ) : (
          author
        ))}
      {author && dated ? ' · ' : ''}
      {dated}
    </p>
  );
}
