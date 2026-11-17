import { useCallback, useState } from 'react';
import { errorText, isGone } from '../utils/api';
import { fieldErrors } from '../utils/field-errors';
import { keys, translate as t } from '../utils/i18n';

/** A dialog's failure state: field messages next to their inputs, and one
 *  general message for everything else (including a 404, which also tells the
 *  caller to refresh its list through `onGone`).
 *
 *  `shown` lists the field paths the form has a place for. A 422 entry for one
 *  of them lands at that field; an entry for any other leaves the general
 *  message up as well, so a failed save never ends with nothing visible. */
export function useFormErrors(gone?: string, onGone?: () => void, shown: readonly string[] = []) {
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const reset = useCallback(() => {
    setError(null);
    setFields({});
  }, []);
  const fail = useCallback(
    (e: unknown) => {
      const mapped = fieldErrors(e);
      const paths = Object.keys(mapped);
      if (paths.length > 0) {
        const visible = Object.fromEntries(
          Object.entries(mapped).filter(([p]) => shown.includes(p)),
        );
        setFields(visible);
        setError(
          Object.keys(visible).length < paths.length ? t(keys.events.errors.invalid_input) : null,
        );
        return;
      }
      setFields({});
      setError(errorText(e, gone));
      if (isGone(e)) onGone?.();
    },
    [gone, onGone, shown],
  );
  const setField = useCallback(
    (name: string, message: string) => setFields((current) => ({ ...current, [name]: message })),
    [],
  );
  const clearField = useCallback(
    (name: string) =>
      setFields((current) => {
        if (!(name in current)) return current;
        const { [name]: _dropped, ...rest } = current;
        return rest;
      }),
    [],
  );
  return { error, fields, reset, fail, setField, clearField };
}
