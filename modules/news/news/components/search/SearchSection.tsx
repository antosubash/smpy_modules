import type { SearchHit } from '../../utils/searchApi';

interface Props {
  label: string;
  hits: SearchHit[];
  /** How many the section actually has. The list shows only its first few. */
  total: number;
  /** Where the rest live — the section's own list, pre-filtered. */
  moreHref: string;
  moreLabel: string;
}

/** One section of results.
 *
 * The count sits in the heading rather than at the end, because it is what
 * tells you whether to keep reading this section or skip to the next — and
 * "17 more articles" only means something once you know there were 19.
 */
export function SearchSection({ label, hits, total, moreHref, moreLabel }: Props) {
  if (total === 0) return null;

  const remaining = total - hits.length;

  return (
    <section aria-label={`${label} results`} data-testid="search-section" data-section={label}>
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label} · {total}
      </h2>

      <ul className="space-y-2">
        {hits.map((hit) => (
          <li key={`${label}-${hit.id}`} data-testid="search-hit">
            <a
              href={hit.url}
              className="block rounded-lg border bg-card p-3 transition hover:bg-muted"
            >
              <p className="font-medium">{hit.title || 'Untitled'}</p>
              <p className="text-sm text-muted-foreground">{hit.subtitle}</p>
              {hit.excerpt && (
                <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{hit.excerpt}</p>
              )}
            </a>
          </li>
        ))}
      </ul>

      {remaining > 0 && (
        <a href={moreHref} className="mt-2 inline-block text-sm text-primary hover:underline">
          {remaining} more {moreLabel} →
        </a>
      )}
    </section>
  );
}
