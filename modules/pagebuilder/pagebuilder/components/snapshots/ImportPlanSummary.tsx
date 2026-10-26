import { Badge } from '@simple-module-py/ui/components/ui/badge';

import { keys, useT } from '../../utils/i18n';
import type { ImportPlan, PagePlanEntry } from '../../utils/snapshotsApi';
import { PlanGroup, type PlanGroupItem } from './PlanGroup';
import {
  describeLayoutSide,
  describeOverwrite,
  overwritesAnything,
  overwriteWarning,
  planTotals,
  untouchedNote,
} from './planSummary';
import { SectionPlans } from './SectionPlan';

/** A page bucket's rows, in the shape the shared plan bucket renders. */
function pageItems(
  entries: PagePlanEntry[],
  describe?: (entry: PagePlanEntry) => string | null,
): PlanGroupItem[] {
  return entries.map((entry) => ({
    // A slug is unique per language, so two translations share one.
    key: `${entry.locale ?? ''}:${entry.slug}`,
    title: entry.title || entry.slug,
    slug: entry.slug,
    locale: entry.locale,
    detail: describe?.(entry) ?? null,
  }));
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
  const { t } = useT();
  const totals = planTotals(plan);
  const untouched = untouchedNote(plan);

  return (
    <div className="space-y-6">
      <p
        className={
          overwritesAnything(plan) ? 'text-sm font-medium text-amber-700' : 'text-sm font-medium'
        }
      >
        {overwriteWarning(plan)}
      </p>

      <PlanGroup
        title={t(keys.pagebuilder.plan.group_overwritten)}
        count={plan.pages.overwritten.length}
        items={pageItems(plan.pages.overwritten, describeOverwrite)}
        tone="warning"
      />
      <PlanGroup
        title={t(keys.pagebuilder.plan.group_created)}
        count={plan.pages.new.length}
        items={pageItems(plan.pages.new)}
      />
      <PlanGroup
        title={t(keys.pagebuilder.plan.group_unchanged)}
        count={plan.pages.unchanged.length}
        items={pageItems(plan.pages.unchanged)}
      />

      <div className="space-y-2">
        <h3 className="text-sm font-medium">{t(keys.pagebuilder.plan.site_layout)}</h3>
        <p className="text-sm text-muted-foreground">
          {describeLayoutSide('header', plan.layout.header, plan.layout.header_present)}
          {', '}
          {describeLayoutSide('footer', plan.layout.footer, plan.layout.footer_present)}.
        </p>
      </div>

      {(totals.redirectsAdded > 0 ||
        totals.redirectsRemoved > 0 ||
        totals.redirectsDropped > 0) && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">{t(keys.pagebuilder.plan.redirects)}</h3>
          <div className="flex flex-wrap gap-2 text-xs">
            {totals.redirectsAdded > 0 && (
              <Badge variant="secondary">+{totals.redirectsAdded}</Badge>
            )}
            {totals.redirectsRemoved > 0 && (
              <Badge variant="secondary">−{totals.redirectsRemoved}</Badge>
            )}
            {totals.redirectsDropped > 0 && (
              <Badge variant="destructive">
                {t(keys.pagebuilder.plan.redirects_dropped, { count: totals.redirectsDropped })}
              </Badge>
            )}
          </div>
          {plan.redirects.dropped.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {t(keys.pagebuilder.plan.dropped_detail, {
                slugs: plan.redirects.dropped.join(', '),
              })}
            </p>
          )}
        </div>
      )}

      {untouched && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">{t(keys.pagebuilder.plan.left_alone)}</h3>
          <p className="text-sm text-muted-foreground">{untouched}</p>
          <ul className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            {plan.pages.untouched.map((entry) => (
              <li key={`${entry.locale ?? ''}:${entry.slug}`} className="font-mono">
                {entry.slug}
              </li>
            ))}
          </ul>
        </div>
      )}

      <SectionPlans plan={plan} />
    </div>
  );
}
