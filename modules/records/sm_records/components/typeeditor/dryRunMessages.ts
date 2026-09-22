/**
 * Humanizes a dry-run failure's `message` (U13a) — `services/_dry_run.py`
 * runs each record's stored `data` back through pydantic against the
 * *proposed* schema, and forwards whatever pydantic says verbatim. That is
 * accurate for a developer and misleading for an operator: making
 * `starts_on` required and checking a record that has never had a value
 * for it comes back `"Input should be a valid date"`, which reads as a
 * formatting problem in the *stored* value — there isn't one, the record
 * simply has none, and the field just stopped being optional.
 *
 * Recognised by a stable substring rather than parsed structurally, the
 * same choice `friendlyImportError` (utils/io.ts) makes for the import
 * parser's own errors: this stays a UI concern, and a message this doesn't
 * recognise is returned unchanged rather than guessed at.
 */

// See `pages/RecordList.tsx` for why `t` is typed this loosely here.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

/** pydantic v2's exact wording for a field with no value at all
 *  (`type: 'missing'`), and for `None` reaching a type-specific validator —
 *  which is what a *required* field with no stored value looks like from
 *  here, since the dry-run has no other way to tell "missing" from
 *  "malformed" apart. Both patterns end in the type name pydantic quotes
 *  ("valid date", "valid integer", "valid string", …). */
const MISSING_VALUE_PATTERN = /^(Field required|Input should be a valid [a-z ]+)$/;

export function humanizeDryRunMessage(t: Translate, message: string): string {
  if (MISSING_VALUE_PATTERN.test(message.trim())) {
    return t('records.type_editor.preview.error_missing_value', {
      defaultValue: 'required, but this record has no value for it',
    });
  }
  return message;
}
