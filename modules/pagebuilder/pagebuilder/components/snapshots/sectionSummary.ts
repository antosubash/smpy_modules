/**
 * The wording of contributed bundle sections (#80), as pure functions.
 *
 * Pagebuilder knows nothing about any one contributor: every label here is a
 * catalogue key the section itself declared (`label_key`, its lines'
 * `label_key`, `count_label_keys`), resolved when rendered against the host's
 * merged catalogue. A key that does not resolve falls back to the section's
 * name or the count's kind, which is truer than a dotted key and never empty.
 *
 * Kept apart from `planSummary.ts` (pages, layout, redirects) for the same
 * reason the server keeps them apart: this half is generic over sections.
 */

import { keys, translate } from '../../utils/i18n';
import type {
  ApplyResult,
  ImportPlan,
  SectionLabels,
  SectionPlanEntry,
  SectionPlanLine,
  Snapshot,
} from '../../utils/snapshotsApi';
import type { PageRestoreMarker } from '../../utils/types';
import type { PlanGroupItem } from './PlanGroup';

const PAGEBUILDER = 'pagebuilder';

/** A section's name in the reader's language, or its raw name. */
export function sectionLabel(labelKey: string | null | undefined, section: string): string {
  return labelKey ? translate(labelKey, { defaultValue: section }) : section;
}

/**
 * A plan line's heading in the reader's language, or — when the contributor's
 * catalogue is gone (its module disabled after staging) — the key's last
 * segment, spaced: "overwritten", never "news.bundle.plan.overwritten".
 */
export function lineLabel(labelKey: string): string {
  const last = labelKey.split('.').pop() || labelKey;
  return translate(labelKey, { defaultValue: last.replace(/_/g, ' ') });
}

/** Permission names are identifiers, not prose: listed as they are. */
function permissionList(permissions: string[] | undefined): string {
  return (permissions ?? []).join(', ');
}

/** The overwrites every contributed section adds to the approval warning. */
export function sectionOverwrites(plan: ImportPlan): number {
  return (plan.sections ?? []).reduce((sum, entry) => sum + (entry.overwrites || 0), 0);
}

/**
 * Why a section card shows counts and no rows, or `null` when it shows both.
 *
 * Redacted: the reader may not capture the section, so its rows are not
 * theirs to read. Unavailable: the rows could not be read back from where
 * staging put them. Both keep the counts, which is what an approver weighs.
 */
export function sectionMarker(entry: SectionPlanEntry): string | null {
  const label = sectionLabel(entry.label_key, entry.section);
  if (entry.redacted) {
    return translate(keys.pagebuilder.plan.section_redacted, {
      label,
      permissions: permissionList(entry.permissions),
    });
  }
  if (entry.details_unavailable) {
    return translate(keys.pagebuilder.plan.section_details_unavailable, { label });
  }
  return null;
}

/** A section line's rows, in the shape the shared plan bucket renders. */
export function lineItems(line: SectionPlanLine): PlanGroupItem[] {
  return (line.items ?? []).map((item, index) => ({
    key: `${item.locale ?? ''}:${item.slug}:${index}`,
    title: item.title,
    slug: item.slug,
    locale: item.locale,
    detail: item.note_key ? translate(item.note_key, { defaultValue: '' }) || null : null,
  }));
}

export interface SectionNote {
  key: string;
  text: string;
  tone: 'warning' | 'muted';
}

/**
 * Every section the plan names without planning it, warnings first.
 *
 * Denied (the stager may not restore it) and skipped (no module here reads it)
 * mean content in the bundle will not land, so they are warnings. Absent —
 * not in the bundle, or left out when it was captured — leaves the live
 * content as it is, which is a promise rather than a risk.
 */
export function sectionNotes(plan: ImportPlan): SectionNote[] {
  const notes: SectionNote[] = [];
  for (const entry of plan.denied ?? []) {
    notes.push({
      key: `denied:${entry.section}`,
      tone: 'warning',
      text: translate(keys.pagebuilder.plan.section_denied, {
        label: sectionLabel(entry.label_key, entry.section),
        permissions: permissionList(entry.permissions),
      }),
    });
  }
  for (const entry of plan.skipped ?? []) {
    notes.push({
      key: `skipped:${entry.section}`,
      tone: 'warning',
      text: translate(keys.pagebuilder.plan.sections.skipped, { section: entry.section }),
    });
  }
  for (const entry of plan.absent ?? []) {
    const label = sectionLabel(entry.label_key, entry.section);
    notes.push({
      key: `absent:${entry.section}`,
      tone: 'muted',
      text: entry.omitted
        ? translate(keys.pagebuilder.plan.section_omitted, {
            label,
            permissions: permissionList(entry.permissions),
          })
        : translate(keys.pagebuilder.plan.sections.absent, { label }),
    });
  }
  return notes;
}

function labelsFor(labels: SectionLabels[], section: string): SectionLabels | undefined {
  return labels.find((entry) => entry.section === section);
}

/** "Articles: 4 · Tags: 2", each kind named by the section's own key. */
export function countParts(
  counts: Record<string, number>,
  countLabelKeys: Record<string, string> = {},
  { skipZero = false }: { skipZero?: boolean } = {},
): string {
  return Object.entries(counts)
    .filter(([, count]) => typeof count === 'number' && !(skipZero && count === 0))
    .map(([kind, count]) =>
      translate(keys.pagebuilder.snapshot_list.section_count, {
        label: countLabelKeys[kind]
          ? translate(countLabelKeys[kind], { defaultValue: kind })
          : kind,
        count,
      }),
    )
    .join(' · ');
}

/**
 * A snapshot's contributed contents, one line per section, then what its
 * capture left out. A section this host does not register is still listed —
 * by its raw name and count kinds — because the bundle does carry it.
 */
export function sectionContents(snapshot: Snapshot, labels: SectionLabels[]): string[] {
  const lines: string[] = [];
  for (const entry of snapshot.manifest?.contents ?? []) {
    if (entry.section === PAGEBUILDER || !entry.counts) continue;
    const known = labelsFor(labels, entry.section);
    lines.push(
      translate(keys.pagebuilder.snapshot_list.section_line, {
        section: sectionLabel(known?.label_key, entry.section),
        counts: countParts(entry.counts, known?.count_label_keys),
      }),
    );
  }
  for (const entry of snapshot.manifest?.omitted ?? []) {
    lines.push(
      translate(keys.pagebuilder.snapshot_list.section_omitted, {
        label: sectionLabel(
          entry.label_key ?? labelsFor(labels, entry.section)?.label_key,
          entry.section,
        ),
        permissions: permissionList(entry.permissions),
      }),
    );
  }
  return lines;
}

/** What an approved restore wrote in each contributed section, for the toast. */
export function appliedSections(result: ApplyResult, labels: SectionLabels[]): string[] {
  return Object.entries(result.sections ?? {}).flatMap(([section, counts]) => {
    const known = labelsFor(labels, section);
    const parts = countParts(counts, known?.count_label_keys, { skipZero: true });
    if (!parts) return [];
    return [
      translate(keys.pagebuilder.import_review.applied_section, {
        section: sectionLabel(known?.label_key, section),
        counts: parts,
      }),
    ];
  });
}

/** The sections an approved restore left out, for the toast's warning. */
export function deniedSections(result: ApplyResult): string[] {
  return (result.denied_sections ?? []).map((entry) =>
    translate(keys.pagebuilder.plan.section_denied, {
      label: sectionLabel(entry.label_key, entry.section),
      permissions: permissionList(entry.permissions),
    }),
  );
}

/** "Also restored with it: News (3)" under a page's restore marker. */
export function restoredWith(marker: PageRestoreMarker): string | null {
  const sections = marker.sections ?? [];
  if (sections.length === 0) return null;
  return translate(keys.pagebuilder.history.restored_with, {
    sections: sections
      .map((entry) =>
        translate(keys.pagebuilder.history.restored_section, {
          label: sectionLabel(entry.label_key, entry.section),
          count: entry.count,
        }),
      )
      .join(', '),
  });
}

/** The footnote under the snapshot list: what a snapshot does not carry. */
export function snapshotFootnote(labels: SectionLabels[]): string {
  if (labels.length === 0) return translate(keys.pagebuilder.snapshots.footnote);
  return translate(keys.pagebuilder.snapshots.footnote_with_sections, {
    sections: labels.map((entry) => sectionLabel(entry.label_key, entry.section)).join(', '),
  });
}
