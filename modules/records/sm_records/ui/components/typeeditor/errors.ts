import type { ValidationError } from '../../utils/types';
import { TOP_LEVEL_ERROR_FIELDS } from './types';

/** First message for `field`, or `undefined`. Shared by the metadata form
 *  and the field rows so a 422's `errors[]` lands on the right input. */
export function fieldMessage(errors: ValidationError[], field: string): string | undefined {
  return errors.find((e) => e.field === field)?.message;
}

/** What the server calls an error that belongs to the payload as a whole
 *  rather than to one input — `schema/compile.py::_public_name` and
 *  `schema/_keys.py::FieldSchemaError(None, …)`, e.g. "every field needs a
 *  'key'" for a row whose key was never typed. */
export const ROOT_ERROR_FIELD = '__root__';

/** The id of the input each top-level `errors[].field` belongs to. Mirrors
 *  the `ID` maps in `TypeMetadataForm`, `PointerFields`, `IconField`,
 *  `CollectionField`, `PublicField` and `SidebarField`; `fields` is the one
 *  top-level name with no input of its own (the whole list is its input),
 *  so it is deliberately absent and falls through to the field rows. */
const METADATA_INPUT_IDS: Record<string, string> = {
  key: 'type-editor-key',
  label: 'type-editor-label',
  label_plural: 'type-editor-label-plural',
  description: 'type-editor-description',
  icon: 'type-editor-icon',
  collection: 'type-editor-collection',
  is_public: 'type-editor-is-public',
  translatable: 'type-editor-translatable',
  show_in_menu: 'type-editor-show-in-menu',
  display_field: 'type-editor-display-field',
  slug_field: 'type-editor-slug-field',
};

export type GroupedErrors = {
  /** Owned by a type-level input — `TypeMetadataForm` and `PointerFields`. */
  topLevel: ValidationError[];
  /** Owned by a field row, matched on the row's `key`. */
  rows: ValidationError[];
  /**
   * Everything else: `__root__`, and anything naming a key no row carries.
   *
   * These used to be handed to the field list and then silently dropped by
   * it, because no row's key matched — so a save refused with "every field
   * needs a 'key'" changed nothing on screen at all and Save read as dead
   * (UX review R6, verification PARTIAL). They have no input to sit under,
   * so the save bar renders them itself.
   */
  unplaceable: ValidationError[];
};

/** Split a 422's `errors[]` three ways: what an input owns, what a row
 *  owns, and what nothing on screen owns. */
export function groupErrors(
  errors: ValidationError[],
  fieldKeys: readonly string[],
): GroupedErrors {
  const keys = new Set(fieldKeys);
  const groups: GroupedErrors = { topLevel: [], rows: [], unplaceable: [] };
  for (const error of errors) {
    if (TOP_LEVEL_ERROR_FIELDS.has(error.field)) groups.topLevel.push(error);
    else if (error.field !== ROOT_ERROR_FIELD && keys.has(error.field)) groups.rows.push(error);
    else groups.unplaceable.push(error);
  }
  return groups;
}

/** Where a refused save should take the eye: an input id, or the index of a
 *  field row (whose inputs only exist once the row is expanded). */
export type InvalidTarget = { inputId: string } | { rowIndex: number } | null;

/**
 * The first refusal in document order — the metadata form sits above the
 * field list, so a top-level error wins over a row one.
 *
 * `null` when nothing on screen owns the refusal (an unplaceable error
 * only): there is no input to go to, and the save bar's alert is the whole
 * answer.
 */
export function firstInvalidTarget(
  groups: GroupedErrors,
  fieldKeys: readonly string[],
): InvalidTarget {
  for (const error of groups.topLevel) {
    const inputId = METADATA_INPUT_IDS[error.field];
    if (inputId) return { inputId };
  }
  const named = new Set(groups.rows.map((error) => error.field));
  const rowIndex = fieldKeys.findIndex((key) => named.has(key));
  return rowIndex === -1 ? null : { rowIndex };
}

/** How many separate inputs a refusal is asking about — the count the save
 *  bar's summary says out loud. Distinct fields, not messages: one field
 *  can come back with two. */
export function invalidFieldCount(groups: GroupedErrors): number {
  return new Set([...groups.topLevel, ...groups.rows].map((error) => error.field)).size;
}
