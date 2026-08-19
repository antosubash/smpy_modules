import type { MediaUsage } from '../../utils/mediaApi';

interface Props {
  usages: MediaUsage[];
  total: number;
}

/** Which pages depend on this asset.
 *
 * Named rather than counted, because "used in 3 places" is not actionable and
 * the reason anyone reads this list is to go and detach it from one of them.
 */
export function MediaUsageList({ usages, total }: Props) {
  if (total === 0) {
    return (
      <p
        data-testid="media-usage"
        data-total="0"
        className="rounded-md border border-dashed p-3 text-sm text-muted-foreground"
      >
        Not used on any page. Deleting it will not break anything.
      </p>
    );
  }

  return (
    <section data-testid="media-usage" data-total={total} aria-label="Pages using this asset">
      <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Used in {total} {total === 1 ? 'place' : 'places'}
      </h2>
      <ul className="space-y-2">
        {usages.map((usage) => (
          <li key={usage.page_id}>
            <a
              href={`/pagebuilder/${usage.page_id}/edit`}
              className="flex items-baseline justify-between gap-3 rounded-lg border bg-card p-3 transition hover:bg-muted"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium">{usage.title}</span>
                <span className="block truncate text-sm text-muted-foreground">
                  /p/{usage.slug}
                </span>
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {/* Worth distinguishing: a reference only the draft carries is a
                    weaker claim on the asset than one that is live. */}
                {usage.draft_only ? 'draft only' : usage.status}
              </span>
            </a>
          </li>
        ))}
      </ul>
      {total > usages.length && (
        <p className="mt-2 text-sm text-muted-foreground">and {total - usages.length} more</p>
      )}
    </section>
  );
}
