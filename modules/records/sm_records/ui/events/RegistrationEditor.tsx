/** Records' part of the event editor's Registration section: pick the registration form (a records
 *  type of kind `registration`) the event registers into, or make one. Who may see which form is
 *  decided by the server's list; the attendee link is shown only when the server gave one. */
import type { RegistrationEditorProps } from '@simple-module-py/events';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useCallback, useEffect, useState } from 'react';
import { keys, useT } from '../utils/i18n';
import {
  createRegistrationForm,
  listRegistrationForms,
  type RegistrationFormList,
} from '../utils/registration-forms-api';

type State = { kind: 'loading' } | { kind: 'error' } | ({ kind: 'ready' } & RegistrationFormList);

export default function RegistrationEditor({
  target,
  onChange,
  capacity,
  readOnly,
  errors,
}: RegistrationEditorProps) {
  const { t } = useT();
  const copy = keys.records.events.registration;
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [creating, setCreating] = useState(false);
  const [failed, setFailed] = useState(false);
  const load = useCallback(async () => {
    setState({ kind: 'loading' });
    try {
      setState({ kind: 'ready', ...(await listRegistrationForms()) });
    } catch {
      setState({ kind: 'error' });
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function create() {
    setCreating(true);
    setFailed(false);
    try {
      const made = await createRegistrationForm();
      await load();
      onChange(made.key);
    } catch {
      setFailed(true);
    } finally {
      setCreating(false);
    }
  }

  if (state.kind === 'loading')
    return (
      <p role="status" className="text-sm text-muted-foreground">
        {t(copy.loading)}
      </p>
    );
  if (state.kind === 'error')
    return (
      <p role="alert" className="text-sm text-destructive">
        {t(copy.load_failed)}{' '}
        <button type="button" className="underline" onClick={() => void load()}>
          {t(copy.retry)}
        </button>
      </p>
    );
  const chosen = state.items.find((form) => form.key === target);
  const unlisted = target !== null && !chosen;
  return (
    <div className="grid gap-3" data-testid="records-registration-editor">
      <div className="grid gap-2">
        <Label htmlFor="records-registration-form">{t(copy.label)}</Label>
        <NativeSelect
          id="records-registration-form"
          value={target ?? ''}
          disabled={readOnly}
          aria-invalid={errors.target ? true : undefined}
          aria-describedby={errors.target ? 'records-registration-form-error' : undefined}
          onChange={(e) => onChange(e.target.value || null)}
        >
          <option value="">{t(copy.choose)}</option>
          {unlisted ? <option value={target}>{target}</option> : null}
          {state.items.map((form) => (
            <option key={form.key} value={form.key}>
              {form.label}
            </option>
          ))}
        </NativeSelect>
        <FieldError id="records-registration-form-error">{errors.target}</FieldError>
      </div>
      {chosen && !chosen.enabled ? (
        <p role="status" className="text-sm text-muted-foreground">
          {t(copy.switched_off)}
        </p>
      ) : null}
      {chosen && !chosen.double_opt_in && capacity !== null ? (
        <p role="alert" className="rounded-md border border-amber-500 p-2 text-sm">
          {t(copy.no_double_opt_in)}
        </p>
      ) : null}
      {chosen?.attendees_url ? (
        <a className="text-sm underline" href={chosen.attendees_url}>
          {t(copy.attendees)}
        </a>
      ) : null}
      {state.can_create && !readOnly ? (
        <div className="grid gap-2">
          <Button type="button" variant="outline" disabled={creating} onClick={() => void create()}>
            {t(creating ? copy.creating : copy.create)}
          </Button>
          {failed ? (
            <p role="alert" className="text-sm text-destructive">
              {t(copy.create_failed)}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
