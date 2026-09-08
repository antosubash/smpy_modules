/**
 * The wording decisions behind the import review screen.
 *
 * Pure functions rather than JSX so they can be unit-tested: this repo's
 * vitest runs in `node` with no DOM, and these are the parts where being
 * wrong actually costs something — an approver who misreads how much is
 * about to be overwritten, or who assumes their other pages are being
 * deleted, makes the wrong call on a live site.
 */

import { keys, translate } from '../../utils/i18n';
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

/** "1 page" / "3 pages" — one place to decide how a count reads.
 *
 *  Every string in this file goes through `translate` rather than a hook:
 *  these are pure functions their callers invoke while rendering, which is
 *  what keeps them unit-testable without a DOM. `translate` reads the shared
 *  i18next instance at call time, so that stays true. */
function pluralize(key: string, count: number): string {
  return translate(key, { count });
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
  if (overwritten === 0) return translate(keys.pagebuilder.plan.overwrite_none);
  return pluralize(keys.pagebuilder.plan.overwrite, overwritten);
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
  return pluralize(keys.pagebuilder.plan.untouched, untouched);
}

/** "12 pages · 3 redirects · 11 media" — a snapshot's contents in one line. */
export function contentsLine(snapshot: Snapshot): string {
  const counts = snapshot.manifest?.counts;
  if (!counts) return translate(keys.pagebuilder.plan.empty_snapshot);
  const parts = [
    pluralize(keys.pagebuilder.plan.page_count, counts.pages),
    pluralize(keys.pagebuilder.plan.redirect_count, counts.redirects),
    translate(keys.pagebuilder.plan.media_count, { count: counts.media }),
  ];
  return parts.join(' · ');
}

const SOURCE_LABELS: Record<Snapshot['source'], string> = {
  manual: keys.pagebuilder.plan.source_manual,
  upload: keys.pagebuilder.plan.source_upload,
  pre_restore: keys.pagebuilder.plan.source_pre_restore,
};

export function sourceLabel(source: Snapshot['source']): string {
  // The raw value is the fallback for a source this build does not know — it
  // is not translatable, and saying it is truer than saying nothing.
  return SOURCE_LABELS[source] ? translate(SOURCE_LABELS[source]) : source;
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
  return translate(keys.pagebuilder.plan.missing_media, {
    count: missing.length,
    files: missing.join(', '),
  });
}

/**
 * Describe one side of the layout for the approval screen.
 *
 * A bundle that does not carry a side leaves the live one untouched — the
 * restore treats an absent key as "no change requested". Saying "0 block(s)"
 * for that read as "this will empty your header", and was indistinguishable
 * from a bundle carrying an explicitly empty header, which does empty it.
 */
export function describeLayoutSide(
  side: 'header' | 'footer',
  count: number,
  present?: boolean,
): string {
  // A key per side rather than a translated noun spliced into a sentence: the
  // footer half reads mid-sentence and is lowercase in English, which is not a
  // property any other language has to share.
  if (present === false) {
    return translate(
      side === 'header'
        ? keys.pagebuilder.plan.layout_header_unchanged
        : keys.pagebuilder.plan.layout_footer_unchanged,
    );
  }
  return translate(
    side === 'header'
      ? keys.pagebuilder.plan.layout_header_blocks
      : keys.pagebuilder.plan.layout_footer_blocks,
    { count },
  );
}
