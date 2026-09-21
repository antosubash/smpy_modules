import type { InvalidTarget } from './errors';

/**
 * Take the person to the input a refused schema save is about (UX review
 * R6) — the type editor's half of what `useRecordEditor::focusInvalidInput`
 * does for a record.
 *
 * Everything here is deferred a tick, for the same reason it is there and
 * one more of its own: the message is React state, and a refusal that names
 * a field also has to wait for `FieldList` to expand that row (its own
 * effect does the expanding, and the row's inputs are not in the DOM until
 * the render that follows). Scroll *and* focus — a focused control below
 * the fold is not "identified to the user" in the sense WCAG 3.3.1 means.
 */

/** Only an enabled control can take focus, and a field row's Key input is
 *  disabled on every field the type already had (the immutable-key rule),
 *  so the row's first *focusable* input is the honest target. */
const FOCUSABLE = 'input:not([disabled]), select:not([disabled]), textarea:not([disabled])';

function rowElement(index: number): HTMLElement | null {
  return document.querySelector<HTMLElement>(
    `[data-testid="records-field-row"][data-field-index="${index}"]`,
  );
}

/**
 * A field row, once it has opened.
 *
 * The opening is `FieldList`'s own effect, one `setState` away from the DOM,
 * and which of the two commits lands first is not something either side can
 * promise — so the row is asked for its inputs, given a frame if it has none
 * yet, and failing that focused on the summary's toggle. The toggle is
 * always there, carries the field's key as its label and its "Needs
 * attention" badge, so the eye and the screen reader both land on the right
 * row either way; it is a worse place to *type* than the inputs, not a
 * worse place to arrive.
 */
function focusRow(index: number, attempt: number): void {
  const row = rowElement(index);
  if (!row) return;
  row.scrollIntoView({ block: 'center', behavior: 'smooth' });
  const input = row.querySelector<HTMLElement>(FOCUSABLE);
  if (input) {
    input.focus({ preventScroll: true });
    return;
  }
  if (attempt === 0) {
    window.requestAnimationFrame(() => focusRow(index, 1));
    return;
  }
  row
    .querySelector<HTMLElement>('[data-testid="records-field-toggle"]')
    ?.focus({ preventScroll: true });
}

function go(target: InvalidTarget): void {
  if (!target) return;
  if ('inputId' in target) {
    const input = document.getElementById(target.inputId);
    if (!input) return;
    input.scrollIntoView({ block: 'center', behavior: 'smooth' });
    input.focus({ preventScroll: true });
    return;
  }
  focusRow(target.rowIndex, 0);
}

export function focusInvalidTarget(target: InvalidTarget): void {
  if (!target || typeof document === 'undefined') return;
  window.setTimeout(() => go(target), 0);
}

/** Whether an element is wholly on screen right now. Read *before* any
 *  scrolling, to decide whether a refusal rendered next to Save also needs
 *  saying somewhere the eye is. */
export function isOnScreen(id: string): boolean {
  if (typeof document === 'undefined') return true;
  const element = document.getElementById(id);
  if (!element) return false;
  const rect = element.getBoundingClientRect();
  return rect.top >= 0 && rect.bottom <= (window.innerHeight || 0);
}
