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
import { useCallback, useMemo, useRef, useState } from 'react';

import { humanizeDryRunMessage } from '../utils/dry-run-messages';
import { displayFieldKey } from '../utils/errors-display';
import { asObject, baselineOf, pretty, stable } from '../utils/record-form-helpers';
import type { RecordRead, TypeRead, ValidationError } from '../utils/types';
import { buildValidator, type Translate } from '../utils/validation';
import { buildPayload, type FormValues, toFormValues } from '../utils/values';

export function useRecordForm(
  type: TypeRead,
  record: RecordRead | null,
  /** "Save as copy" (Missing-item): the duplicate source's data, only ever
   *  passed when `record` is `null` (a fresh new-record visit). `dirty`
   *  still has to compare against a *blank* record, not this — leaving a
   *  prefilled-but-unsaved copy must warn the same as typing into an
   *  ordinary new record would (R12c), so only the seed values below read
   *  it; `baseline` (further down) deliberately does not. */
  initialData?: Record<string, unknown> | null,
) {
  const { t } = useT();
  const fields = type.fields;
  const seedData = record?.data ?? initialData ?? null;

  const [values, setValues] = useState<FormValues>(() => toFormValues(fields, seedData));
  const [original, setOriginal] = useState<Record<string, unknown> | null>(seedData);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});
  const [serverErrors, setServerErrors] = useState<ValidationError[]>([]);
  // `record.invalid` — "marked, not hidden" (design §8.3): a record a
  // restrictive schema change or a schema rollback no longer fits. Kept
  // separate from `serverErrors` so a fresh 422 (checked below) can override
  // it without a save first having to clear it, and so `reset()` can
  // re-derive it from whatever the next response actually says.
  const [invalidErrors, setInvalidErrors] = useState<ValidationError[]>(record?.invalid ?? []);
  const [raw, setRaw] = useState(false);
  const [rawText, setRawText] = useState(() => pretty(seedData));
  const [rawError, setRawError] = useState<string | null>(null);
  const [baseline, setBaseline] = useState(() => baselineOf(fields, record?.data ?? null));
  /** The key the editor should take the person to when a save is refused by
   *  the client validator (R6). A ref and not state: `validateAndBuild`'s
   *  caller reads it in the same tick it returns `null`, before React has
   *  re-rendered anything. */
  const firstInvalidRef = useRef<string | null>(null);

  // `t` is cast rather than typed through i18next's own signature: calling it
  // behind an alias makes tsc bail with "type instantiation is excessively
  // deep". `Translate` in `utils/validation.ts` says why this is the bridge.
  const validator = useMemo(() => buildValidator(t as unknown as Translate, fields), [t, fields]);

  const fieldKeys = useMemo(() => new Set(fields.map((field) => field.key)), [fields]);

  // Read by `setValue`'s clear-on-fix pass, which runs inside a state
  // updater and so cannot close over the render's `values` without going
  // stale on two edits in one tick.
  const valuesRef = useRef<FormValues>(values);
  valuesRef.current = values;

  /** Per-field messages. Precedence, low to high: the record's own
   *  `invalid` marker (stale until the next save), the client validator's
   *  courtesy check, then the server's 422 — the freshest server opinion
   *  always wins the tie.
   *
   *  U9: `invalidErrors` carries pydantic's own wording verbatim (design
   *  §8.3), same as a dry-run report's `sample[].errors` — humanized here
   *  too, so "required, but this record has no value for it" reads the same
   *  under this input as it does in the type editor's own report for the
   *  same condition. `clientErrors`/`serverErrors` are this module's own
   *  copy already. */
  const fieldErrors = useMemo(() => {
    const merged: Record<string, string> = {};
    for (const entry of invalidErrors) {
      const key = displayFieldKey(entry.field);
      if (fieldKeys.has(key)) merged[key] = humanizeDryRunMessage(t, entry.message);
    }
    Object.assign(merged, clientErrors);
    for (const entry of serverErrors) {
      // The API reports a bare field key; tolerate a `data.`-prefixed one so
      // a future change to the error envelope cannot silently hide messages.
      const key = displayFieldKey(entry.field);
      if (fieldKeys.has(key)) merged[key] = entry.message;
    }
    return merged;
  }, [invalidErrors, clientErrors, serverErrors, fieldKeys, t]);

  /** The 422s that are about the record envelope, not a schema field —
   *  `status`, `slug`, `position`, and anything this build cannot place. */
  const envelopeErrors = useMemo(
    () =>
      serverErrors.filter((entry) => {
        const key = displayFieldKey(entry.field);
        return !fieldKeys.has(key);
      }),
    [serverErrors, fieldKeys],
  );

  /** Clear-on-fix (R6). A client error that only recomputes on the next Save
   *  stays red under an input the person has already corrected, which teaches
   *  them to ignore inline validation. Only a key that *already* complains is
   *  re-checked: validating as you first type a required field would shout
   *  "This field is required" at an empty box nobody has finished filling. */
  const setValue = useCallback(
    (key: string, next: unknown) => {
      setValues((prev) => ({ ...prev, [key]: next }));
      setClientErrors((errors) => {
        if (!(key in errors)) return errors;
        const message = validator({ ...valuesRef.current, [key]: next })[key];
        if (message === errors[key]) return errors;
        const { [key]: _fixed, ...rest } = errors;
        return message === undefined ? rest : { ...rest, [key]: message };
      });
    },
    [validator],
  );

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
      setInvalidErrors(next.invalid ?? []);
      setRawError(null);
      setBaseline(baselineOf(fields, next.data));
    },
    [fields],
  );

  /** Are the values on screen different from the record as it was loaded
   *  (or last saved)? The unsaved-changes guard's whole input (R12c).
   *
   * Raw JSON that will not parse counts as dirty: it is certainly not what
   * the server has, and "you typed something we can't read" is exactly when
   * leaving silently would hurt most. */
  const dirty = useMemo(() => {
    if (raw) {
      const parsed = asObject(rawText);
      return parsed === null ? true : stable(parsed) !== baseline;
    }
    return stable(buildPayload(fields, values, original)) !== baseline;
  }, [raw, rawText, fields, values, original, baseline]);

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
    firstInvalidRef.current = null;
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
    if (Object.keys(found).length > 0) {
      // *First* in the order the fields are rendered, not in whatever order
      // the validator's object happens to enumerate: the person is being
      // taken to it, so it has to be the topmost one on screen (R6).
      firstInvalidRef.current = fields.find((field) => field.key in found)?.key ?? null;
      return null;
    }
    return buildPayload(fields, values, original);
  }, [raw, rawText, validator, values, fields, original, t]);

  /** The key `validateAndBuild` stopped on, for the caller that focuses and
   *  scrolls to it. `null` once a save gets past the client validator. */
  const firstInvalidKey = useCallback(() => firstInvalidRef.current, []);

  return {
    values,
    setValue,
    fieldErrors,
    envelopeErrors,
    serverErrors,
    setServerErrors,
    /** How many fields the last client-side validation is still unhappy
     *  about — falls as they are fixed because `setValue` re-checks (R6). */
    clientErrorCount: Object.keys(clientErrors).length,
    /** The count the editor's "N fields need attention" summary next to Save
     *  actually reports (U5). `validateAndBuild` clears `serverErrors` before
     *  it runs, so a save that reached the server already passed the client
     *  validator — the two counts are never simultaneously nonzero, and
     *  falling back to the server one gives a 409 collision or a 422 the same
     *  role="alert" treatment the client path always had. Distinct field
     *  keys, not raw error count: a collision sets exactly one entry, but a
     *  422 naming both a schema field and `slug` should read "2", not risk
     *  double-counting a field two error sources happen to both mention. */
    errorCount:
      Object.keys(clientErrors).length > 0
        ? Object.keys(clientErrors).length
        : new Set(serverErrors.map((entry) => displayFieldKey(entry.field))).size,
    clearErrors,
    reset,
    raw,
    rawText,
    setRawText,
    rawError,
    toggleRaw,
    validateAndBuild,
    firstInvalidKey,
    currentPayloadText,
    dirty,
  };
}
