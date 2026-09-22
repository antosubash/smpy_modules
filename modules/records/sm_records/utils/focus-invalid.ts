/**
 * Where a refused save takes the person.
 *
 * Split out of `hooks/useRecordEditor.ts` (300-line cap) — it is plain DOM
 * work over ids the editor hands it, with no state of its own, and both the
 * 422 path and the client validator's path call it.
 */

import { fieldIdForKey } from '../components/fields/FieldShell';

/** The envelope inputs a 422 or a collision 409 can name, and the ids
 *  `RecordEnvelopeFields` gives them — a schema field's id comes from
 *  `fieldIdForKey` instead. */
const ENVELOPE_INPUT_IDS: Record<string, string> = {
  status: 'record-status',
  slug: 'record-slug',
  position: 'record-position',
};

/**
 * Take the person to the input a refused save is about (UX review R6).
 *
 * Deferred a tick: the message that names the field is React state, and on
 * the slug's path it also has to open the "Advanced" disclosure it lives in
 * — neither is in the DOM while the click handler that called this is still
 * running. Focus *and* scroll, because a focused input below the fold is not
 * "identified to the user" in the sense WCAG 3.3.1 means.
 */
export function focusInvalidInput(key: string): void {
  if (typeof document === 'undefined') return;
  const id = ENVELOPE_INPUT_IDS[key] ?? fieldIdForKey(key);
  window.setTimeout(() => {
    const input = document.getElementById(id);
    // A group control (a checkbox list, the relation picker) has no element
    // at that id; its label does, and scrolling there is still the right
    // answer even though there is nothing to focus.
    const anchor = input ?? document.getElementById(`${id}-label`);
    if (!anchor) return;
    anchor.scrollIntoView({ block: 'center', behavior: 'smooth' });
    if (input instanceof HTMLElement) input.focus({ preventScroll: true });
  }, 0);
}

/** The envelope inputs in the order `RecordEditor` renders them: `status`
 *  sits in the header above the fields, `slug` and `position` in the
 *  "Advanced" disclosure below them. */
const BEFORE_FIELDS = ['status'];
const AFTER_FIELDS = ['slug', 'position'];

/** `data.title` → `title`; a bare key is returned as it came. */
export function bareFieldKey(field: string): string {
  return field.startsWith('data.') ? field.slice(5) : field;
}

/**
 * Which refusal to take the person to, out of a 422 naming several (R17).
 *
 * **First in the order the inputs are rendered**, not first in whatever
 * order the server happened to enumerate — the wording is
 * `useRecordForm`'s, which has always done this for the client validator's
 * own errors, and the two paths should not disagree. A 422 could otherwise
 * scroll to the bottom field while an error sat above the fold.
 *
 * A key this screen has no input for keeps its position relative to the
 * other unplaceable ones and sorts after everything it can place — there is
 * nothing to scroll to, so it must not win the race against something there
 * is.
 */
export function firstErrorInDomOrder(
  errors: readonly { field: string }[],
  fieldKeys: readonly string[],
): string | null {
  const order = [...BEFORE_FIELDS, ...fieldKeys, ...AFTER_FIELDS];
  let best: { key: string; rank: number } | null = null;
  for (const entry of errors) {
    const key = bareFieldKey(entry.field);
    const index = order.indexOf(key);
    const rank = index === -1 ? Number.MAX_SAFE_INTEGER : index;
    if (best === null || rank < best.rank) best = { key, rank };
  }
  return best?.key ?? null;
}
