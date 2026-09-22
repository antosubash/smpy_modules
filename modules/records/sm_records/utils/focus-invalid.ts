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
