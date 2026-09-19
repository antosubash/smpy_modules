/**
 * All of `RecordEditor`'s payload state in one hook: the per-field form
 * values, the client validator, the server's 422s, and the raw-JSON escape
 * hatch that has to round-trip with the fields.
 *
 * Extracted from the page because `pages/` may hold nothing but real Inertia
 * pages — `import.meta.glob` derives a page name from that path — and because
 * the editor would otherwise run past the 300-line cap.
 *
 * **Server errors override client ones.** The client validator is a courtesy
 * mirror of `sm_records/schema/_builders.py`; the server sees things it
 * cannot (uniqueness, a relation target that has since been trashed), so on
 * any field where both have an opinion the 422's message is what shows.
 */

import { useT } from '@simple-module-py/i18n';
import { useCallback, useMemo, useState } from 'react';

import type { RecordRead, TypeRead, ValidationError } from '../utils/types';
import { buildValidator, type Translate } from '../utils/validation';
import { buildPayload, type FormValues, toFormValues } from '../utils/values';

function asObject(text: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(text);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

function pretty(data: Record<string, unknown> | null): string {
  return JSON.stringify(data ?? {}, null, 2);
}

export type RecordFormState = ReturnType<typeof useRecordForm>;

export function useRecordForm(type: TypeRead, record: RecordRead | null) {
  const { t } = useT();
  const fields = type.fields;

  const [values, setValues] = useState<FormValues>(() =>
    toFormValues(fields, record?.data ?? null),
  );
  const [original, setOriginal] = useState<Record<string, unknown> | null>(record?.data ?? null);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});
  const [serverErrors, setServerErrors] = useState<ValidationError[]>([]);
  const [raw, setRaw] = useState(false);
  const [rawText, setRawText] = useState(() => pretty(record?.data ?? null));
  const [rawError, setRawError] = useState<string | null>(null);

  // `t` is cast rather than typed through i18next's own signature: calling it
  // behind an alias makes tsc bail with "type instantiation is excessively
  // deep". `Translate` in `utils/validation.ts` says why this is the bridge.
  const validator = useMemo(() => buildValidator(t as unknown as Translate, fields), [t, fields]);

  const fieldKeys = useMemo(() => new Set(fields.map((field) => field.key)), [fields]);

  /** Per-field messages, with the server's winning any tie. */
  const fieldErrors = useMemo(() => {
    const merged: Record<string, string> = { ...clientErrors };
    for (const entry of serverErrors) {
      // The API reports a bare field key; tolerate a `data.`-prefixed one so
      // a future change to the error envelope cannot silently hide messages.
      const key = entry.field.startsWith('data.') ? entry.field.slice(5) : entry.field;
      if (fieldKeys.has(key)) merged[key] = entry.message;
    }
    return merged;
  }, [clientErrors, serverErrors, fieldKeys]);

  /** The 422s that are about the record envelope, not a schema field —
   *  `status`, `slug`, `position`, and anything this build cannot place. */
  const envelopeErrors = useMemo(
    () =>
      serverErrors.filter((entry) => {
        const key = entry.field.startsWith('data.') ? entry.field.slice(5) : entry.field;
        return !fieldKeys.has(key);
      }),
    [serverErrors, fieldKeys],
  );

  const setValue = useCallback((key: string, next: unknown) => {
    setValues((prev) => ({ ...prev, [key]: next }));
  }, []);

  const clearErrors = useCallback(() => {
    setClientErrors({});
    setServerErrors([]);
    setRawError(null);
  }, []);

  /** Replace everything from a record the server just handed back — the
   *  conflict panel's "reload", and the save path's refresh. */
  const reset = useCallback(
    (next: RecordRead) => {
      setValues(toFormValues(fields, next.data));
      setOriginal(next.data);
      setRawText(pretty(next.data));
      setClientErrors({});
      setServerErrors([]);
      setRawError(null);
    },
    [fields],
  );

  /** The payload as it stands, valid or not — for the conflict panel's
   *  read-only "your version" pane. */
  const currentPayloadText = useCallback(
    () => (raw ? rawText : pretty(buildPayload(fields, values, original))),
    [raw, rawText, fields, values, original],
  );

  /** Flip between the generic form and the raw-JSON editor.
   *
   * Leaving raw mode *refuses* while the JSON is invalid: re-populating the
   * fields from text that will not parse would silently discard the edit. */
  const toggleRaw = useCallback(() => {
    if (!raw) {
      setRawText(pretty(buildPayload(fields, values, original)));
      setRawError(null);
      setRaw(true);
      return;
    }
    const parsed = asObject(rawText);
    if (!parsed) {
      setRawError(t('records.editor.invalid_json', { defaultValue: 'Invalid JSON' }));
      return;
    }
    setValues(toFormValues(fields, parsed));
    setClientErrors({});
    setRawError(null);
    setRaw(false);
  }, [raw, rawText, fields, values, original, t]);

  /** Validate and produce the `data` object to send, or `null` when the
   *  editor should stay put and show what is wrong. Raw mode skips the
   *  field validator on purpose — it is the escape hatch for a payload the
   *  generic form cannot express, and the server still has the last word. */
  const validateAndBuild = useCallback((): Record<string, unknown> | null => {
    setServerErrors([]);
    setRawError(null);
    if (raw) {
      const parsed = asObject(rawText);
      if (!parsed) {
        setRawError(t('records.editor.invalid_json', { defaultValue: 'Invalid JSON' }));
        return null;
      }
      setClientErrors({});
      // `_orphaned` stays visible in the raw editor — it's part of what the
      // record actually stores — but it is never the caller's to write
      // (services/_payload.py 422s the whole save if it's present). Strip it
      // from what's submitted rather than from the display.
      const { _orphaned: _submittedOrphaned, ...submittable } = parsed;
      return submittable;
    }
    const found = validator(values);
    setClientErrors(found);
    if (Object.keys(found).length > 0) return null;
    return buildPayload(fields, values, original);
  }, [raw, rawText, validator, values, fields, original, t]);

  return {
    values,
    setValue,
    fieldErrors,
    envelopeErrors,
    serverErrors,
    setServerErrors,
    clearErrors,
    reset,
    raw,
    rawText,
    setRawText,
    rawError,
    toggleRaw,
    validateAndBuild,
    currentPayloadText,
  };
}
