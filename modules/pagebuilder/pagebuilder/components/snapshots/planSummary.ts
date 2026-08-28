/**
 * The wording decisions behind the import review screen.
 *
 * Pure functions rather than JSX so they can be unit-tested: this repo's
 * vitest runs in `node` with no DOM, and these are the parts where being
 * wrong actually costs something — an approver who misreads how much is
 * about to be overwritten, or who assumes their other pages are being
 * deleted, makes the wrong call on a live site.
 */

import type { ImportPlan, Snapshot } from '../../utils/snapshotsApi';

export interface PlanTotals {
  created: number;
  overwritten: number;
  unchanged: number;
  untouched: number;
  redirectsAdded: number;
  redirectsRemoved: number;
  redirectsDropped: number;
}

export function planTotals(plan: ImportPlan): PlanTotals {
  return {
    created: plan.pages.new.length,
    overwritten: plan.pages.overwritten.length,
    unchanged: plan.pages.unchanged.length,
    untouched: plan.pages.untouched.length,
    redirectsAdded: plan.redirects.added.length,
    redirectsRemoved: plan.redirects.removed.length,
    redirectsDropped: plan.redirects.dropped.length,
  };
}

/**
 * The headline an approver reads first.
 *
 * Leads with the overwrite count because that is the only irreversible-feeling
 * part of the decision, and says nothing alarming when nothing is at risk —
 * a screen that shouts on every restore trains people to stop reading it.
 */
export function overwriteWarning(plan: ImportPlan): string {
  const { overwritten } = planTotals(plan);
  if (overwritten === 0) return 'No existing page will be overwritten.';
  if (overwritten === 1) return '1 page will be overwritten.';
  return `${overwritten} pages will be overwritten.`;
}

/**
 * What happens to pages the bundle does not mention.
 *
 * Stated explicitly because the intuition runs the other way: "restore" sounds
 * like "make the site match this snapshot", and someone assuming that would
 * reject a good bundle to protect pages that were never at risk.
 */
export function untouchedNote(plan: ImportPlan): string | null {
  const { untouched } = planTotals(plan);
  if (untouched === 0) return null;
  const subject = untouched === 1 ? '1 page is' : `${untouched} pages are`;
  const object = untouched === 1 ? 'It' : 'They';
  return `${subject} on this site but not in this snapshot. ${object} will not be deleted.`;
}

/** "12 pages · 3 redirects · 11 media" — a snapshot's contents in one line. */
export function contentsLine(snapshot: Snapshot): string {
  const counts = snapshot.manifest?.counts;
  if (!counts) return 'Empty snapshot';
  const parts = [
    `${counts.pages} ${counts.pages === 1 ? 'page' : 'pages'}`,
    `${counts.redirects} ${counts.redirects === 1 ? 'redirect' : 'redirects'}`,
    `${counts.media} media`,
  ];
  return parts.join(' · ');
}

const SOURCE_LABELS: Record<Snapshot['source'], string> = {
  manual: 'Taken here',
  upload: 'Uploaded',
  pre_restore: 'Automatic, before a restore',
};

export function sourceLabel(source: Snapshot['source']): string {
  return SOURCE_LABELS[source] ?? source;
}

/**
 * Whether a snapshot's own capture reported media it could not find.
 *
 * A row whose file is missing on disk is not fatal to capture, but restoring
 * such a snapshot silently loses that image — so the list has to say so.
 */
export function missingMediaWarning(snapshot: Snapshot): string | null {
  const missing = snapshot.manifest?.missing_media ?? [];
  if (missing.length === 0) return null;
  return `${missing.length} file(s) were missing when this was taken: ${missing.join(', ')}`;
}
