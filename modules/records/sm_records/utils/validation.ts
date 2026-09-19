/**
 * Client-side mirror of the server's payload validation.
 *
 * The server is the authority — `sm_records/schema/_builders.py` is what
 * actually decides a write, and every rule below exists there first. This is
 * a courtesy so the common mistakes are caught before a round trip; a 422
 * still wins on screen (see `useRecordForm`), because the server can refuse
 * things this cannot see (uniqueness, a relation target that vanished).
 *
 * `buildValidator` takes `t` rather than importing it, so every message is
 * built inside the component's `useMemo` with `t` in its dependencies. A
 * validator built at module scope freezes against the first render's locale.
 */

import type { FieldDef } from './types';
import { choicesOf, fieldConstraints, isRelationValue, relationIsMany } from './values';

/** The subset of i18next's `t` this module needs.
 *
 * Deliberately a plain function type rather than `ReturnType<typeof useT>['t']`:
 * i18next's own signature is generic enough that calling it through an alias
 * makes `tsc` give up with "type instantiation is excessively deep". The one
 * `t as unknown as Translate` that bridges the two lives in `useRecordForm`. */
export type Translate = (
  key: string,
  options: { defaultValue: string; [name: string]: unknown },
) => string;
export type Validator = (values: Record<string, unknown>) => Record<string, string>;

/** `Numeric(19, 5)` — design §7.3, and `NUMBER_SCALE` in `constants.py`. */
const NUMBER_SCALE = 5;
const MAX_INT_DIGITS = 14;
/** `MEDIA_MAX_LEN` in `schema/_builders.py`. */
const MEDIA_MAX_LEN = 500;

const DECIMAL_RE = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/;
const INTEGER_RE = /^[+-]?\d+$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const UUID_RE = /^[0-9a-f]{32}$/;
const TYPE_KEY_RE = /^[a-z][a-z0-9_]*$/;
// Deliberately loose, exactly as the server's `_EMAIL_RE` is: this catches
// the typo, it does not implement RFC 5322.
const EMAIL_RE = /^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$/;

function numberOr(value: unknown, fallback: number | null): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function isEmptyValue(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

function checkTextConstraints(t: Translate, field: FieldDef, text: string): string | undefined {
  const constraints = fieldConstraints(field);
  const min = numberOr(constraints.min_length, null);
  const max = numberOr(constraints.max_length, null);
  if (min !== null && text.length < min) {
    return t('records.validation.min_length', {
      defaultValue: 'Must be at least {{min}} characters',
      min,
    });
  }
  if (max !== null && text.length > max) {
    return t('records.validation.max_length', {
      defaultValue: 'Must be at most {{max}} characters',
      max,
    });
  }
  const pattern = constraints.pattern;
  if (typeof pattern === 'string' && pattern) {
    try {
      // `re.search`, not `re.match` — the server uses `pattern.search`.
      if (!new RegExp(pattern).test(text)) {
        return t('records.validation.pattern', {
          defaultValue: 'Does not match the required format',
        });
      }
    } catch {
      // A pattern JS cannot compile is the type editor's problem, not this
      // record's; leave it to the server rather than blocking the save.
    }
  }
  return undefined;
}

function checkUrl(t: Translate, text: string): string | undefined {
  const message = t('records.validation.url', {
    defaultValue: 'Must be an http:// or https:// URL with a host',
  });
  try {
    const parsed = new URL(text);
    if ((parsed.protocol !== 'http:' && parsed.protocol !== 'https:') || !parsed.host) {
      return message;
    }
  } catch {
    return message;
  }
  return undefined;
}

function checkNumber(t: Translate, field: FieldDef, text: string): string | undefined {
  if (!DECIMAL_RE.test(text)) {
    return t('records.validation.not_a_number', { defaultValue: 'Not a number' });
  }
  const [whole, fraction = ''] = text.replace(/^[+-]/, '').split('.');
  if (fraction.length > NUMBER_SCALE) {
    return t('records.validation.decimals', {
      defaultValue: 'At most {{scale}} decimal places are stored',
      scale: NUMBER_SCALE,
    });
  }
  if (whole.replace(/^0+(?=\d)/, '').length > MAX_INT_DIGITS) {
    return t('records.validation.int_digits', {
      defaultValue: 'At most {{digits}} digits before the decimal point',
      digits: MAX_INT_DIGITS,
    });
  }
  // Comparison only — the value itself never leaves this module as a float.
  return checkRange(t, field, Number(text));
}

function checkRange(t: Translate, field: FieldDef, value: number): string | undefined {
  const constraints = fieldConstraints(field);
  const min = numberOr(constraints.min, null);
  const max = numberOr(constraints.max, null);
  if (min !== null && value < min) {
    return t('records.validation.min', { defaultValue: 'Must be at least {{min}}', min });
  }
  if (max !== null && value > max) {
    return t('records.validation.max', { defaultValue: 'Must be at most {{max}}', max });
  }
  return undefined;
}

function checkChoice(t: Translate, field: FieldDef, value: unknown): string | undefined {
  const allowed = new Set(choicesOf(field).map((choice) => choice.value));
  const unknownChoice = t('records.validation.choice', {
    defaultValue: 'Not one of the configured choices',
  });
  if (field.type === 'select') {
    return typeof value === 'string' && allowed.has(value) ? undefined : unknownChoice;
  }
  if (!Array.isArray(value)) return unknownChoice;
  if (new Set(value).size !== value.length) {
    return t('records.validation.duplicate_choice', { defaultValue: 'Contains duplicate values' });
  }
  return value.every((item) => typeof item === 'string' && allowed.has(item))
    ? undefined
    : unknownChoice;
}

function checkJson(t: Translate, text: string): string | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return t('records.validation.json', { defaultValue: 'Not valid JSON' });
  }
  if (parsed === null || typeof parsed !== 'object') {
    return t('records.validation.json_shape', {
      defaultValue: 'Must be a JSON object or array, not a scalar',
    });
  }
  return undefined;
}

function refIsValid(value: unknown): boolean {
  if (!isRelationValue(value)) return false;
  return TYPE_KEY_RE.test(value.type) && UUID_RE.test(value.uuid);
}

function checkRelation(t: Translate, field: FieldDef, value: unknown): string | undefined {
  const message = t('records.validation.relation', {
    defaultValue: 'Not a valid link to a record',
  });
  if (relationIsMany(field)) {
    return Array.isArray(value) && value.every(refIsValid) ? undefined : message;
  }
  return refIsValid(value) ? undefined : message;
}

function checkOne(t: Translate, field: FieldDef, value: unknown): string | undefined {
  switch (field.type) {
    case 'text':
    case 'longtext':
      return checkTextConstraints(t, field, String(value));
    case 'email': {
      const text = String(value);
      return (
        checkTextConstraints(t, field, text) ??
        (EMAIL_RE.test(text)
          ? undefined
          : t('records.validation.email', { defaultValue: 'Not a valid email address' }))
      );
    }
    case 'url': {
      const text = String(value);
      return checkTextConstraints(t, field, text) ?? checkUrl(t, text);
    }
    case 'media':
      return String(value).length > MEDIA_MAX_LEN
        ? t('records.validation.max_length', {
            defaultValue: 'Must be at most {{max}} characters',
            max: MEDIA_MAX_LEN,
          })
        : undefined;
    case 'number':
      return checkNumber(t, field, String(value).trim());
    case 'integer': {
      const text = String(value).trim();
      if (!INTEGER_RE.test(text)) {
        return t('records.validation.not_an_integer', { defaultValue: 'Must be a whole number' });
      }
      // Same cap `number` gets (F8): the wire value is the trimmed digit
      // string now, not a parsed JS number, so a value past
      // `Number.isSafeInteger` needs its own length check rather than
      // relying on `Number()` to have already lost precision on the way in.
      if (text.replace(/^[+-]/, '').replace(/^0+(?=\d)/, '').length > MAX_INT_DIGITS) {
        return t('records.validation.int_digits', {
          defaultValue: 'At most {{digits}} digits before the decimal point',
          digits: MAX_INT_DIGITS,
        });
      }
      return checkRange(t, field, Number(text));
    }
    case 'boolean':
      return typeof value === 'boolean'
        ? undefined
        : t('records.validation.boolean', { defaultValue: 'Expected true or false' });
    case 'date': {
      const text = String(value).trim();
      const parsed = new Date(`${text}T00:00:00Z`);
      return DATE_RE.test(text) && !Number.isNaN(parsed.getTime())
        ? undefined
        : t('records.validation.date', { defaultValue: 'Not a valid date (YYYY-MM-DD)' });
    }
    case 'datetime':
      return Number.isNaN(new Date(String(value).trim()).getTime())
        ? t('records.validation.datetime', { defaultValue: 'Not a valid date and time' })
        : undefined;
    case 'select':
    case 'multiselect':
      return checkChoice(t, field, value);
    case 'json':
      return checkJson(t, String(value));
    case 'relation':
      return checkRelation(t, field, value);
    default:
      // A type this build does not know is edited as read-only JSON by
      // `UnknownField`; the server decides it.
      return undefined;
  }
}

/** Build the per-field validator for one Record Type's schema. */
export function buildValidator(t: Translate, fields: FieldDef[]): Validator {
  return (values) => {
    const errors: Record<string, string> = {};
    for (const field of fields) {
      const value = values[field.key];
      if (isEmptyValue(value)) {
        if (field.required) {
          errors[field.key] = t('records.validation.required', {
            defaultValue: 'This field is required',
          });
        }
        continue;
      }
      const message = checkOne(t, field, value);
      if (message) errors[field.key] = message;
    }
    return errors;
  };
}
