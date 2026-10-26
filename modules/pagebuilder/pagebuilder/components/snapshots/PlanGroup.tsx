/** One row of a plan bucket: what it is, where it lives, and what happens to it. */
export interface PlanGroupItem {
  key: string;
  title: string;
  /** The address, shown in mono beside the title. */
  slug?: string;
  /** A content language, for a section whose rows carry one. */
  locale?: string | null;
  /** Right-aligned detail: block changes, or a contributor's note. */
  detail?: string | null;
}

/**
 * One bucket of the plan, hidden entirely when it is empty.
 *
 * An empty "0 pages removed" row is noise on a screen whose whole job is to
 * make the one number that matters easy to find. Shared by pagebuilder's own
 * page buckets and every contributed section's lines (#80), so an approver
 * reads a news line exactly as they read a page one.
 *
 * `count` is separate from `items` because a reader who may not see a
 * section's rows still sees how many there are: the heading stands, the list
 * is simply not there.
 */
export function PlanGroup({
  title,
  count,
  items,
  tone,
}: {
  title: string;
  count: number;
  items: PlanGroupItem[];
  tone?: 'warning' | null;
}) {
  if (count === 0) return null;
  const warning = tone === 'warning';
  return (
    <div className="space-y-2">
      <h3 className={warning ? 'text-sm font-medium text-amber-700' : 'text-sm font-medium'}>
        {title} <span className="text-muted-foreground">({count})</span>
      </h3>
      {items.length > 0 && (
        <ul className="divide-y rounded-md border text-sm">
          {items.map((item) => (
            <li
              key={item.key}
              className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-3 py-2"
            >
              <span className={warning ? 'min-w-0 break-words font-medium' : 'min-w-0 break-words'}>
                {item.locale && (
                  <span className="mr-2 rounded bg-muted px-1 font-mono text-xs uppercase text-muted-foreground">
                    {item.locale}
                  </span>
                )}
                {item.title || item.slug}
                {item.slug && item.slug !== item.title && (
                  <span className="ml-2 break-all font-mono text-xs text-muted-foreground">
                    {item.slug}
                  </span>
                )}
              </span>
              {item.detail && (
                <span className="shrink-0 text-xs text-muted-foreground">{item.detail}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
