/**
 * Content i18n: pull the human copy out of a stored page, and write
 * translations back into the same shape.
 *
 * Pure functions with no storage of their own — same as upstream. Nothing in
 * this module decides *where* a translated document lives; that is a schema
 * question for whichever host wants the feature.
 *
 * Distinct from UI i18n (the editor's own English strings), which is tracked
 * separately in CLAUDE.md.
 */

export { applyTranslatedStrings } from './apply';
export {
  type ExtractResult,
  extractTranslatableStrings,
  type FieldPath,
  type PathSegment,
} from './extract';
export { isTranslatableField, TRANSLATABLE_TEXT_TYPES } from './translatable-fields';
