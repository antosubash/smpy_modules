/**
 * The name a record shows when it has no `display_title`.
 *
 * A type's `display_field` is optional (design §7), so `display_title` can
 * be `""` — most visibly on the Invalid worklist, where the field that would
 * have supplied it is often the very one now failing validation (U5). Left
 * as-is, an empty title leaves the title cell's link with no text to click
 * and the row's own `aria-label`s reading "Select ", "Delete " — a WCAG
 * 4.1.2 failure on exactly the controls the bulk work added names to.
 *
 * The fallback is the type's label and the record's own short uuid, neither
 * of which requires a value nobody gave the record: every row stays
 * distinct and legible, and a real title always wins once one exists.
 */

/** The first 8 hex characters of a uuid, with an ellipsis marking it as
 *  shortened — the same slice `DryRunReportView`/`LastAppliedReport` already
 *  take, just with the visual cue that this one exists to be read on its
 *  own rather than sit next to the whole error it came from. */
export function shortUuid(uuid: string): string {
  return `${uuid.slice(0, 8)}…`;
}

/** `display_title`, or `"{type label} {short uuid}"` when the record has
 *  none. */
export function recordDisplayTitle(
  record: { display_title: string; uuid: string },
  type: { label: string },
): string {
  return record.display_title || `${type.label} ${shortUuid(record.uuid)}`;
}
