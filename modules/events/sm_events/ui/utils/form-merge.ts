import type { FormState, TextForm } from './event-form';

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
/** One value of a three-way merge: what the user changed since `started` stays,
 *  anything they left alone takes the newer server value. */
const pick = <T>(started: T, mine: T, theirs: T): T => (same(mine, started) ? theirs : mine);

function mergeText(
  started: TextForm | undefined,
  mine: TextForm | undefined,
  theirs: TextForm | undefined,
): TextForm | undefined {
  if (!mine || !started || !theirs) return pick(started, mine, theirs);
  const out = { ...theirs };
  for (const key of Object.keys(theirs) as (keyof TextForm)[]) {
    (out as Record<string, unknown>)[key] = pick(started[key], mine[key], theirs[key]);
  }
  return out;
}

/** The form to show after a refused action: `theirs` (the newer server version)
 *  with the edits the user typed since `started` laid on top, field by field. */
export function mergeOnto(started: FormState, mine: FormState, theirs: FormState): FormState {
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(theirs) as (keyof FormState)[]) {
    if (key !== 'texts') out[key] = pick(started[key], mine[key], theirs[key]);
  }
  const texts: Record<string, TextForm> = {};
  const locales = new Set([
    ...Object.keys(started.texts),
    ...Object.keys(mine.texts),
    ...Object.keys(theirs.texts),
  ]);
  for (const locale of locales) {
    const merged = mergeText(started.texts[locale], mine.texts[locale], theirs.texts[locale]);
    if (merged) texts[locale] = merged;
  }
  out.texts = texts;
  return out as FormState;
}
