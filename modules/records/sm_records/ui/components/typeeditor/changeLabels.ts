/**
 * Translating a `SchemaChange`/`SchemaPreview.kind` into a catalogue key, in
 * one place — `SchemaChangeList` and `ChangeKindBadge` both need it. The keys
 * are tables of `keys.records…` leaves rather than template literals, so `tsc`
 * checks each against `en.json`. Pure and dependency-free so
 * `changeLabels.test.ts` can enumerate every member of the closed `what` set
 * without a component to render.
 */

import { keys, type Translate } from '../../utils/i18n';
import type { ChangeClass } from '../../utils/types';

/** Mirrors the server's closed `SchemaChange.what` set (design §8.2) — every
 *  member the preview endpoint can send, enumerated so each has a catalogue
 *  key rather than a guess. An unrecognised `what` still renders (as the raw
 *  value itself), because a value this build doesn't know about is more
 *  useful shown than swallowed. */
export const CHANGE_WHAT_KEYS: Record<string, string> = {
  field_added: keys.records.type_editor.change.field_added,
  field_removed: keys.records.type_editor.change.field_removed,
  type_changed: keys.records.type_editor.change.type_changed,
  required_added: keys.records.type_editor.change.required_added,
  required_removed: keys.records.type_editor.change.required_removed,
  unique_added: keys.records.type_editor.change.unique_added,
  unique_removed: keys.records.type_editor.change.unique_removed,
  indexed_on: keys.records.type_editor.change.indexed_on,
  indexed_off: keys.records.type_editor.change.indexed_off,
  constraint_tightened: keys.records.type_editor.change.constraint_tightened,
  constraint_relaxed: keys.records.type_editor.change.constraint_relaxed,
  choice_added: keys.records.type_editor.change.choice_added,
  choice_removed: keys.records.type_editor.change.choice_removed,
  options_changed: keys.records.type_editor.change.options_changed,
  label_changed: keys.records.type_editor.change.label_changed,
  display_field_changed: keys.records.type_editor.change.display_field_changed,
};

const CHANGE_KIND_KEYS: Record<ChangeClass, string> = {
  additive: keys.records.type_editor.preview.kind_additive,
  index_affecting: keys.records.type_editor.preview.kind_index_affecting,
  restrictive: keys.records.type_editor.preview.kind_restrictive,
  destructive: keys.records.type_editor.preview.kind_destructive,
};

export function changeWhatLabel(t: Translate, what: string): string {
  const key = CHANGE_WHAT_KEYS[what];
  return key ? t(key) : what;
}

export function changeKindLabel(t: Translate, kind: ChangeClass): string {
  return t(CHANGE_KIND_KEYS[kind]);
}
