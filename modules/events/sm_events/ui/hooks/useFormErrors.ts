import { useCallback, useState } from 'react';
import { errorText, isGone } from '../utils/api';
import { fieldErrors } from '../utils/field-errors';

/** A dialog's failure state: field messages next to their inputs, and one
 *  general message for everything else (including a 404, which also tells the
 *  caller to refresh its list through `onGone`). */
export function useFormErrors(gone?: string, onGone?: () => void) {
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const reset = useCallback(() => {
    setError(null);
    setFields({});
  }, []);
  const fail = useCallback(
    (e: unknown) => {
      const mapped = fieldErrors(e);
      if (Object.keys(mapped).length > 0) {
        setFields(mapped);
        setError(null);
        return;
      }
      setError(errorText(e, gone));
      if (isGone(e)) onGone?.();
    },
    [gone, onGone],
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
