import { Badge } from '@simple-module-py/ui/components/ui/badge';

import type { ImportPlan, PagePlanEntry } from '../../utils/snapshotsApi';
import { describeLayoutSide, overwriteWarning, planTotals, untouchedNote } from './planSummary';

/** One bucket of the plan, hidden entirely when it is empty.
 *
 * An empty "0 pages removed" row is noise on a screen whose whole job is to
 * make the one number that matters easy to find.
 */
function Group({
  title,
  entries,
  tone,
  describe,
}: {
  title: string;
  entries: PagePlanEntry[];
  tone?: 'warning';
  describe?: (entry: PagePlanEntry) => string | null;
}) {
  if (entries.length === 0) return null;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">
        {title} <span className="text-muted-foreground">({entries.length})</span>
      </h3>
      <ul className="divide-y rounded-md border text-sm">
        {entries.map((entry) => (
          <li key={entry.slug} className="flex items-baseline justify-between gap-4 px-3 py-2">
            <span className={tone === 'warning' ? 'font-medium' : undefined}>
              {entry.title || entry.slug}
              <span className="ml-2 font-mono text-xs text-muted-foreground">{entry.slug}</span>
            </span>
            {describe?.(entry) && (
              <span className="shrink-0 text-xs text-muted-foreground">{describe(entry)}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** How a page's blocks differ, when it is one being overwritten. */
function blockSummary(entry: PagePlanEntry): string | null {
  const parts: string[] = [];
  if (entry.added) parts.push(`+${entry.added}`);
  if (entry.removed) parts.push(`−${entry.removed}`);
  if (entry.changed) parts.push(`~${entry.changed}`);
  const blocks = parts.length ? `${parts.join(' ')} blocks` : 'metadata only';
  // Worth saying out loud: this slug looks free, but the page under it is in
  // the trash and the restore overwrites and un-bins it.
  return entry.revived ? `${blocks} · revived from trash` : blocks;
}

/**
 * What applying this bundle would do, ordered by what is at stake.
 *
 * Overwrites first and loudest; pages the bundle does not mention last, with
 * an explicit promise that they survive. The order is the argument: an
 * approver should be able to stop reading after the first line and still have
 * the fact they most needed.
 */
export function ImportPlanSummary({ plan }: { plan: ImportPlan }) {
  const totals = planTotals(plan);
  const untouched = untouchedNote(plan);

  return (
    <div className="space-y-6">
      <p
        className={
          totals.overwritten > 0 ? 'text-sm font-medium text-amber-700' : 'text-sm font-medium'
        }
      >
        {overwriteWarning(plan)}
      </p>

      <Group
        title="Overwritten"
        entries={plan.pages.overwritten}
        tone="warning"
        describe={blockSummary}
      />
      <Group title="Created" entries={plan.pages.new} />
      <Group title="Unchanged" entries={plan.pages.unchanged} />

      <div className="space-y-2">
        <h3 className="text-sm font-medium">Site layout</h3>
        <p className="text-sm text-muted-foreground">
          {describeLayoutSide('Header', plan.layout.header, plan.layout.header_present)}
          {', '}
          {describeLayoutSide('footer', plan.layout.footer, plan.layout.footer_present)}.
        </p>
      </div>

      {(totals.redirectsAdded > 0 ||
        totals.redirectsRemoved > 0 ||
        totals.redirectsDropped > 0) && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Redirects</h3>
          <div className="flex flex-wrap gap-2 text-xs">
            {totals.redirectsAdded > 0 && (
              <Badge variant="secondary">+{totals.redirectsAdded}</Badge>
            )}
            {totals.redirectsRemoved > 0 && (
              <Badge variant="secondary">−{totals.redirectsRemoved}</Badge>
            )}
            {totals.redirectsDropped > 0 && (
              <Badge variant="destructive">
                {totals.redirectsDropped} dropped — target missing
              </Badge>
            )}
          </div>
          {plan.redirects.dropped.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Dropped: {plan.redirects.dropped.join(', ')}. A redirect pointing at a page that does
              not exist would only produce a 404.
            </p>
          )}
        </div>
      )}

      {untouched && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Left alone</h3>
          <p className="text-sm text-muted-foreground">{untouched}</p>
          <ul className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            {plan.pages.untouched.map((entry) => (
              <li key={entry.slug} className="font-mono">
                {entry.slug}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
