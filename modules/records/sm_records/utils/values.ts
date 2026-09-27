/**
 * Form-value ⇄ wire-value conversion for the schema-driven record editor.
 *
 * The form holds *editable* shapes (a text input's string, a checkbox's
 * boolean, a `datetime-local`'s naive local string); the API holds the wire
 * shapes design §7.3/§9 specify. Keeping the two apart in one small module
 * means no field component has to know the wire contract, and the one rule
 * that is easy to break by accident lives in exactly one place:
 *
 * **A `number` is a string on the wire and stays a string in form state.**
 * The server stores `Numeric(19, 5)` and serialises it as `"9.99"`. Parsing
 * it to a JS float and re-serialising is precisely the round-trip the
 * five-decimal contract exists to prevent, so this module never calls
 * `parseFloat` on a `number` value — it only ever measures the digits.
 *
 * **A `datetime` always carries an offset.** The server refuses a naive
 * value outright, and a `datetime-local` input produces nothing else, so
 * `toApiValue` stamps the browser's current offset on the way out.
 */

import type { FieldDef } from './types';

export type FormValues = Record<string, unknown>;

/** What a cell shows when there is no value. A typographic marker rather
 *  than a sentence, so it is not translated — but it is *one* marker, named
 *  once, instead of a bare `'—'` ternary branch in each table (polish note:
 *  that shape is what an untranslated-string check flags, and three files
 *  spelled it separately). */
export const EMPTY_CELL = '—';

/** A `relation` value, as design §9 defines it. */
export type RelationValue = { type: string; uuid: string };

/** Field types whose form value is a plain string. */
const STRING_TYPES = new Set(['text', 'longtext', 'email', 'url', 'media', 'select']);

export function fieldOptions(field: FieldDef): Record<string, unknown> {
  return field.options ?? {};
}

export function fieldConstraints(field: FieldDef): Record<string, unknown> {
  return field.constraints ?? {};
}

export function relationTarget(field: FieldDef): string {
  const target = fieldOptions(field).target_type;
  return typeof target === 'string' ? target : '';
}

export function relationIsMany(field: FieldDef): boolean {
  return fieldOptions(field).many === true;
}

export function isRelationValue(value: unknown): value is RelationValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const obj = value as Record<string, unknown>;
  return typeof obj.type === 'string' && typeof obj.uuid === 'string';
}

/** The `{value, label}` list behind a `select`/`multiselect`. */
export function choicesOf(field: FieldDef): { value: string; label: string }[] {
  const raw = fieldOptions(field).choices;
  if (!Array.isArray(raw)) return [];
  const out: { value: string; label: string }[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue;
    const obj = entry as Record<string, unknown>;
    if (typeof obj.value === 'string') {
      out.push({ value: obj.value, label: typeof obj.label === 'string' ? obj.label : obj.value });
    }
  }
  return out;
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** ISO-with-offset → the naive local string a `datetime-local` input wants.
 *
 * Includes seconds (`HH:MM:SS`) so a value that carries them survives an
 * open-and-save round trip unchanged — an input truncated to `HH:MM` silently
 * zeroes them on every save. Pair with `step="1"` on the input itself, or the
 * browser's own UI never offers a seconds field to type into. */
export function isoToLocalInput(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return '';
  const date = `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`;
  const time = `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`;
  return `${date}T${time}`;
}

/** A `datetime-local` string → ISO 8601 carrying the browser's own offset.
 *
 * Never returns a naive value for input the browser can parse: the server
 * refuses one rather than guessing a zone, and guessing UTC here would shift
 * every timestamp by the viewer's offset. Unparseable text is handed back
 * untouched so the server's message, not a silent fallback, is what the
 * person sees. */
export function localInputToIso(local: string): string {
  const parsed = new Date(local);
  if (Number.isNaN(parsed.getTime())) return local;
  const minutes = -parsed.getTimezoneOffset();
  const sign = minutes < 0 ? '-' : '+';
  const abs = Math.abs(minutes);
  const offset = `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
  const date = `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`;
  const time = `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`;
  return `${date}T${time}${offset}`;
}

/**
 * ISO datetime (with offset) → the viewer's own locale, date + short time.
 *
 * Shared between a schema `datetime` field's cell (`RecordCell`) and the
 * envelope's own fixed timestamps (`published_at`/`updated_at`/`created_at`,
 * design §9) — both are ISO-with-offset on the wire, so the same
 * presentation belongs on both. Rendering the envelope's raw ISO string next
 * to a `datetime` field formatted this way is what actually reads as two
 * different clocks on one row.
 *
 * Unparseable input is handed back unchanged, same as a `datetime` field's
 * own fallback — the point is never to substitute a value for one the
 * browser's `Date` rejects.
 */
export function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    parsed,
  );
}

function asText(raw: unknown): string {
  if (typeof raw === 'string') return raw;
  return raw === null || raw === undefined ? '' : String(raw);
}

/** One stored value → the shape its field component edits. */
export function toFormValue(field: FieldDef, raw: unknown): unknown {
  switch (field.type) {
    case 'boolean':
      // `null` is kept distinct from `false` so opening a record and saving
      // it does not quietly turn every unset optional flag into a `false`.
      return typeof raw === 'boolean' ? raw : null;
    case 'number':
    case 'integer':
      return asText(raw);
    case 'date':
      return typeof raw === 'string' ? raw.slice(0, 10) : '';
    case 'datetime':
      return typeof raw === 'string' ? isoToLocalInput(raw) : '';
    case 'multiselect':
      return Array.isArray(raw)
        ? raw.filter((item): item is string => typeof item === 'string')
        : [];
    case 'json':
      return raw === null || raw === undefined ? '' : JSON.stringify(raw, null, 2);
    case 'relation':
      if (relationIsMany(field)) return Array.isArray(raw) ? raw.filter(isRelationValue) : [];
      return isRelationValue(raw) ? raw : null;
    default:
      return STRING_TYPES.has(field.type) ? asText(raw) : raw;
  }
}

/** One form value → its wire shape, or `undefined` when the field is empty.
 *
 * `original` is the value the server last sent for this field, when the
 * caller has it. It exists for one rule, which is the same rule the header
 * states for `number`: **never re-serialise what was not edited.** A
 * `datetime-local` input holds `HH:MM:SS`, while the server stores and
 * returns microseconds (`…T09:38:38.477871Z`), so opening a record and
 * saving it rewrote every sub-second `datetime` to `.000000` — and, because
 * `useRecordForm` builds its dirty baseline through this same pair, the
 * truncation read as "no unsaved changes", so nothing warned and a save of
 * any *other* field carried it through (R2). When the stored value renders
 * to exactly the string in the input, the stored value is what goes back. */
export function toApiValue(field: FieldDef, value: unknown, original?: unknown): unknown {
  switch (field.type) {
    case 'boolean':
      return typeof value === 'boolean' ? value : undefined;
    case 'number':
    case 'integer':
    case 'date': {
      // Deliberately still a string: see this module's header. `integer` too:
      // `to_int` in `schema/_builders.py` parses the string itself, so a
      // `Number()` here would round anything past 2**53 before the server
      // ever sees it, and non-integer text goes out untouched so the server's
      // own "must be a whole number" is what shows.
      const text = asText(value).trim();
      return text === '' ? undefined : text;
    }
    case 'datetime': {
      const text = asText(value).trim();
      if (text === '') return undefined;
      // Untouched: the input still shows what the stored value renders to,
      // so send the stored value back byte for byte rather than the
      // second-resolution re-serialisation of it.
      if (typeof original === 'string' && isoToLocalInput(original) === text) return original;
      return localInputToIso(text);
    }
    case 'multiselect':
      return Array.isArray(value) && value.length > 0 ? [...value] : undefined;
    case 'json': {
      const text = asText(value).trim();
      if (text === '') return undefined;
      try {
        return JSON.parse(text);
      } catch {
        return text;
      }
    }
    case 'relation': {
      if (relationIsMany(field)) {
        const items = Array.isArray(value) ? value.filter(isRelationValue) : [];
        return items.length > 0 ? items : undefined;
      }
      return isRelationValue(value) ? value : undefined;
    }
    default: {
      if (!STRING_TYPES.has(field.type)) return value === '' || value == null ? undefined : value;
      const text = asText(value);
      return text === '' ? undefined : text;
    }
  }
}

/**
 * The record envelope's `position` input → the integer the API takes, or
 * `null` when what is in the box is not one (R14).
 *
 * `Number(position) || 0` was the old conversion, and it had three silent
 * failures in it: a browser hands back `''` for text a `type="number"`
 * input cannot parse, so typing garbage saved `0` with no message; `1e3`
 * saved `1000`; and `3.7` went to the server to come back as a 422 that
 * this input is the only sensible place to show. Parsed by pattern rather
 * than by `Number`, because every one of those is a number to `Number`.
 *
 * An empty box is *not* zero: the box being empty is exactly what a
 * browser reports for unparseable text, so reading it as 0 is the silent
 * coercion this exists to stop. Clearing the field asks for a number, and
 * `0` is the number that means "unordered".
 */
export function parsePosition(text: string): number | null {
  const trimmed = text.trim();
  if (!/^[+-]?\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isSafeInteger(value) ? value : null;
}

/** Every field's stored value → the form's initial state. */
export function toFormValues(fields: FieldDef[], data: Record<string, unknown> | null): FormValues {
  const out: FormValues = {};
  for (const field of fields) {
    out[field.key] = toFormValue(field, data ? data[field.key] : undefined);
  }
  return out;
}

/** The `data` object a POST/PUT sends.
 *
 * An empty optional is **omitted** rather than sent as `null`, so the field's
 * configured `default` applies — which is what a create wants. On an update
 * `original` is the payload the server just handed back, and a read
 * materialises every key (`from_stored`), so "the key is present" is the same
 * test as "the stored value was explicitly null" *and* it makes clearing a
 * field send `null` instead of silently restoring its default.
 *
 * `_orphaned` is never included, even when `original` carries one: it holds
 * values whose field was deleted (design §8.2), and `services/_payload.py`
 * refuses the key outright on any write — `update_record`
 * (`services/records.py`) carries the stored value forward itself, so a
 * client-sent copy is not merely redundant, it 422s the save.
 */
export function buildPayload(
  fields: FieldDef[],
  values: FormValues,
  original: Record<string, unknown> | null,
): Record<string, unknown> {
  const data: Record<string, unknown> = {};
  for (const field of fields) {
    const wire = toApiValue(field, values[field.key], original ? original[field.key] : undefined);
    if (wire !== undefined) data[field.key] = wire;
    else if (original && Object.hasOwn(original, field.key)) data[field.key] = null;
  }
  return data;
}
