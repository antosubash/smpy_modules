import { useCallback, useEffect, useRef, useState } from 'react';
import { errorText, isGone } from '../utils/api';
import { fieldErrors } from '../utils/field-errors';
import { keys, translate as t } from '../utils/i18n';

/** A dialog's failure state: field messages next to their inputs, and one
 *  general message for everything else (including a 404, which also tells the
 *  caller to refresh its list through `onGone`).
 *
 *  `shown` lists the field paths the form has a place for. A 422 entry for one
 *  of them lands at that field; an entry for any other leaves the general
 *  message up as well, so a failed save never ends with nothing visible.
 *
 *  `codeField` places a coded refusal (`invalid_local_time`, `slug_taken`) at its input.
 *
 *  Attach `formRef` to the `<form>`: after every failed submit focus moves to
 *  the first input marked `aria-invalid` (the first input for a group message), so the failure is announced where the
 *  user is, not left on Save. */
export function useFormErrors(
  gone?: string,
  onGone?: () => void,
  shown: readonly string[] = [],
  codeField?: (error: unknown) => string | undefined,
) {
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [failures, setFailures] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (failures === 0) return;
    // A message for a group of fields (no input is marked) lands on the form's first input.
    const form = formRef.current;
    (
      form?.querySelector<HTMLElement>('[aria-invalid="true"]') ??
      form?.querySelector<HTMLElement>('input, textarea, select')
    )?.focus();
  }, [failures]);
  const reset = useCallback(() => {
    setError(null);
    setFields({});
  }, []);
  const fail = useCallback(
    (e: unknown) => {
      // A refusal that carries a code and no `loc` still belongs to one input.
      const coded = codeField?.(e);
      const mapped = coded ? { [coded]: errorText(e) } : fieldErrors(e);
      const paths = Object.keys(mapped);
      if (paths.length > 0) {
        const visible = Object.fromEntries(
          Object.entries(mapped).filter(([p]) => shown.includes(p) || p.startsWith('extra.')),
        );
        setFields(visible);
        setError(
          Object.keys(visible).length < paths.length ? t(keys.events.errors.invalid_input) : null,
        );
        setFailures((n) => n + 1);
        return;
      }
      setFields({});
      setError(errorText(e, gone));
      if (isGone(e)) onGone?.();
    },
    [gone, onGone, shown, codeField],
  );
  /** The form's own checks failed before any request: show them and focus the first. */
  const reject = useCallback((found: Record<string, string>) => {
    setFields(found);
    setFailures((n) => n + 1);
  }, []);
  const clearField = useCallback(
    (name: string) =>
      setFields((current) => {
        if (!(name in current)) return current;
        const { [name]: _dropped, ...rest } = current;
        return rest;
      }),
    [],
  );
  return { error, fields, formRef, reset, fail, reject, clearField };
}
