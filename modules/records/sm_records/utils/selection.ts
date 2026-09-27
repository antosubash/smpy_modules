/**
 * The record list's selection, as pure functions over a `Set<string>`.
 *
 * Kept out of the hook that owns the state for the usual reason the `utils/`
 * files here exist: every rule worth getting right — what Shift+click means
 * when the anchor is gone, what "select all" does on a half-selected page,
 * what survives a page change — is a question about two arguments and an
 * answer, and testing it through a mounted table would test React instead.
 *
 * The set holds uuids and never indexes: a row's position changes with every
 * sort, filter and page, and a selection keyed by position would silently
 * come to mean different records. Indexes appear only inside `range`, which
 * is about what the operator *saw* between two clicks.
 */

export type Selection = ReadonlySet<string>;

/** Add or remove one uuid. */
export function toggle(selection: Selection, uuid: string): Set<string> {
  const next = new Set(selection);
  if (!next.delete(uuid)) next.add(uuid);
  return next;
}

/**
 * Shift+click: add every uuid between the anchor and `uuid` inclusive, in the
 * order the page is showing them.
 *
 * Always *adds* — a range never deselects, because the gesture that produced
 * it (click one row, Shift+click another) says nothing about what should
 * happen to the rows outside it, and taking a selection away is the surprise
 * nobody asked for. An anchor that is no longer on the page (the list
 * reloaded, or a filter changed under it) degrades to a plain toggle, which
 * is the only honest reading left.
 */
export function range(
  selection: Selection,
  uuids: readonly string[],
  anchor: string | null,
  uuid: string,
): Set<string> {
  const from = anchor === null ? -1 : uuids.indexOf(anchor);
  const to = uuids.indexOf(uuid);
  if (from === -1 || to === -1) return toggle(selection, uuid);
  const next = new Set(selection);
  for (let i = Math.min(from, to); i <= Math.max(from, to); i += 1) next.add(uuids[i]);
  return next;
}

/** Every uuid on this page, added to whatever was already selected. */
export function selectAll(selection: Selection, uuids: readonly string[]): Set<string> {
  return new Set([...selection, ...uuids]);
}

/** This page's uuids removed, leaving any selected on another page alone. */
export function deselectAll(selection: Selection, uuids: readonly string[]): Set<string> {
  const next = new Set(selection);
  for (const uuid of uuids) next.delete(uuid);
  return next;
}

/** Is every row of this page selected? An empty page is not: "select all" on
 *  nothing would otherwise render as already done. */
export function allSelected(selection: Selection, uuids: readonly string[]): boolean {
  return uuids.length > 0 && uuids.every((uuid) => selection.has(uuid));
}

/** Some but not all — the header checkbox's indeterminate state. */
export function someSelected(selection: Selection, uuids: readonly string[]): boolean {
  return uuids.some((uuid) => selection.has(uuid)) && !allSelected(selection, uuids);
}

/**
 * The selection narrowed to the records currently on the page, in page order.
 *
 * What every action sends. A uuid that is no longer listed — purged in
 * another tab, moved out by a filter, left behind on page 1 — is not a record
 * this screen can still claim the operator meant, and sending it would earn a
 * 404 that refuses the whole batch for a row nobody can see.
 */
export function visible(selection: Selection, uuids: readonly string[]): string[] {
  return uuids.filter((uuid) => selection.has(uuid));
}
