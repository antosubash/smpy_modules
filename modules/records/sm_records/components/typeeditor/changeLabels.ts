/**
 * Translating a `SchemaChange`/`SchemaPreview.kind` into an i18n key + a
 * fallback English string, in one place — `SchemaChangeList` and
 * `ChangeKindBadge` both need it, and `useT()`'s key-union signature can't
 * accept a template-literal key directly (see `FieldRow.tsx::keyErrorMessage`
 * for the same shape, applied to key-validation codes instead of change
 * kinds). Pure and dependency-free so `changeLabels.test.ts` can enumerate
 * every member of the closed `what` set without a component to render.
 */

import type { Translate } from '../../utils/translate';
import type { ChangeClass } from '../../utils/types';

/** Mirrors the server's closed `SchemaChange.what` set (design §8.2) — every
 *  member the preview endpoint can send, enumerated so the fallback text
 *  below is complete rather than a guess. An unrecognised `what` still
 *  renders (via the raw value itself as the fallback), because a value this
 *  build doesn't know about is more useful shown than swallowed. */
export const CHANGE_WHAT_DEFAULTS: Record<string, string> = {
  field_added: 'Field added',
  field_removed: 'Field removed',
  type_changed: 'Type changed',
  required_added: 'Made required',
  required_removed: 'No longer required',
  unique_added: 'Made unique',
  unique_removed: 'No longer unique',
  indexed_on: 'Indexing turned on',
  indexed_off: 'Indexing turned off',
  constraint_tightened: 'Constraint tightened',
  constraint_relaxed: 'Constraint relaxed',
  choice_added: 'Choice added',
  choice_removed: 'Choice removed',
  options_changed: 'Options changed',
  label_changed: 'Label changed',
  display_field_changed: "Display title field changed — every record's title will be recomputed",
};

const CHANGE_KIND_DEFAULTS: Record<ChangeClass, string> = {
  additive: 'Additive',
  index_affecting: 'Rebuilds index',
  restrictive: 'Restrictive',
  destructive: 'Removes data',
};

/** The `type_editor.change.<what>` family's key for one `what` value. */
export function changeWhatKey(what: string): string {
  return `records.type_editor.change.${what}`;
}

/** The `type_editor.preview.kind_<kind>` family's key for one `kind`. */
export function changeKindKey(kind: ChangeClass): string {
  return `records.type_editor.preview.kind_${kind}`;
}

export function changeWhatLabel(t: Translate, what: string): string {
  return t(changeWhatKey(what), { defaultValue: CHANGE_WHAT_DEFAULTS[what] ?? what });
}

export function changeKindLabel(t: Translate, kind: ChangeClass): string {
  return t(changeKindKey(kind), { defaultValue: CHANGE_KIND_DEFAULTS[kind] });
}
