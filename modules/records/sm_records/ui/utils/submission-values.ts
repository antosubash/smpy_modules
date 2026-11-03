/**
 * What a `RecordForm` input holds, and what the server is sent (#101).
 *
 * Inputs hold strings (a checkbox a boolean, a multi-select a string list);
 * the payload holds the type's values. A field left empty is **left out**
 * rather than sent as `""`, so a default the type declares applies and an
 * optional number is not refused for being blank. The server is the judge of
 * every value — a number that does not parse is sent as typed and comes back
 * as the field's 422.
 */

import type { SubmissionDefinition, SubmissionField } from './submissions-form-api';

export type FormValue = string | boolean | string[];
export type FormValues = Record<string, FormValue>;

function initial(field: SubmissionField): FormValue {
  const fallback = field.default;
  if (field.type === 'boolean') return fallback === true;
  if (field.type === 'multiselect') {
    return Array.isArray(fallback) ? fallback.map(String) : [];
  }
  return fallback === null || fallback === undefined ? '' : String(fallback);
}

/** Every field's starting value, keeping what the visitor already typed for
 *  a key the new definition still has — a `form_changed` re-render must not
 *  throw the visitor's message away. */
export function valuesFor(definition: SubmissionDefinition, previous: FormValues = {}): FormValues {
  const out: FormValues = {};
  for (const field of definition.fields) {
    const kept = previous[field.key];
    out[field.key] =
      kept !== undefined && typeof kept === typeof initial(field) ? kept : initial(field);
  }
  return out;
}

function isEmpty(value: FormValue | undefined): boolean {
  if (value === undefined || value === false) return true;
  if (Array.isArray(value)) return value.length === 0;
  return typeof value === 'string' && value.trim() === '';
}

/** The required fields with nothing in them — checked before sending, so
 *  the visitor hears it at once and in their language. A required boolean
 *  is a box that must be ticked. */
export function missingRequired(fields: SubmissionField[], values: FormValues): string[] {
  return fields.filter((field) => field.required && isEmpty(values[field.key])).map((f) => f.key);
}

function converted(field: SubmissionField, value: FormValue): unknown {
  if (field.type === 'boolean' || Array.isArray(value)) return value;
  const text = String(value);
  if (field.type === 'number' || field.type === 'integer') {
    const parsed = Number(text.replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : text;
  }
  if (field.type === 'datetime') {
    // `datetime-local` has no zone; the visitor's own clock is what they meant.
    const parsed = new Date(text);
    return Number.isNaN(parsed.getTime()) ? text : parsed.toISOString();
  }
  return text;
}

/** The `data` object of a submission. */
export function payloadFor(fields: SubmissionField[], values: FormValues): Record<string, unknown> {
  const data: Record<string, unknown> = {};
  for (const field of fields) {
    const value = values[field.key];
    if (value === undefined) continue;
    if (field.type !== 'boolean' && isEmpty(value)) continue;
    data[field.key] = converted(field, value);
  }
  return data;
}
