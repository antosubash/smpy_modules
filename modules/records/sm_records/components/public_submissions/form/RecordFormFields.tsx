/**
 * The `<form>` of a `RecordForm` (#101): the problem summary, one input per
 * field of the live definition, the consent box with the server's text, the
 * honeypot, the CAPTCHA and the submit button. Split from
 * `RecordFormRender.tsx` (the states around it) for the 300-line cap.
 */

import type { CSSProperties, FormEvent } from 'react';
import { CONSENT_KEY, type SubmissionForm } from '../../../hooks/useSubmissionForm';
import { keys, useT } from '../../../utils/i18n';
import { CaptchaWidget } from './CaptchaWidget';
import { ERROR_STYLE, HELP_STYLE, LABEL_STYLE, SubmissionInput } from './SubmissionInput';
import type { RecordFormProps } from './types';

const BUTTON_STYLE: CSSProperties = {
  background: 'var(--pb-accent, #2563eb)',
  color: 'var(--pb-accent-contrast, #ffffff)',
};
/** Off-screen rather than `display: none`, which some bots skip. */
const HONEYPOT_STYLE: CSSProperties = {
  position: 'absolute',
  left: '-10000px',
  width: '1px',
  height: '1px',
  overflow: 'hidden',
};

const ps = keys.records.public_submissions;

type FormBodyProps = {
  props: RecordFormProps;
  form: SubmissionForm;
  editing: boolean;
  fieldId: (key: string) => string;
  summaryId: string;
  overrides: Map<string, { label: string; help: string }>;
  subscription: boolean;
  locale: string | undefined;
};

export function FormBody({
  props,
  form,
  editing,
  fieldId,
  summaryId,
  overrides,
  subscription,
  locale,
}: FormBodyProps) {
  const { t } = useT();
  const definition = form.definition;
  if (!definition) return null;
  const sending = form.phase === 'submitting';
  const consentId = fieldId(CONSENT_KEY);
  const consentError = form.fieldErrors[CONSENT_KEY];
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editing) void form.submit();
  };
  const submitLabel = props.submitLabel || t(subscription ? ps.form.subscribe : ps.form.submit);

  return (
    <form noValidate className="relative space-y-4" onSubmit={onSubmit} aria-busy={sending}>
      <div id={summaryId} role="alert" tabIndex={-1} data-testid="records-form-problem">
        {form.problem && (
          <p className="rounded-md border px-3 py-2 text-sm" style={ERROR_STYLE}>
            {t(form.problem.key, form.problem.params)}
          </p>
        )}
      </div>
      {definition.fields.map((field) => {
        const override = overrides.get(field.key);
        const error = form.fieldErrors[field.key];
        return (
          <SubmissionInput
            key={field.key}
            field={field}
            id={fieldId(field.key)}
            label={override?.label || field.label}
            help={override?.help || field.help}
            value={form.values[field.key] ?? ''}
            error={error ? t(error) : null}
            disabled={sending}
            onChange={(value) => form.setValue(field.key, value)}
          />
        );
      })}
      {definition.consent && (
        <div data-testid="records-form-consent">
          <div className="flex items-start gap-2">
            <input
              id={consentId}
              type="checkbox"
              className="mt-1 h-4 w-4"
              checked={form.consent}
              disabled={sending}
              aria-required={definition.consent.required || undefined}
              aria-invalid={consentError ? true : undefined}
              aria-describedby={consentError ? `${consentId}-error` : undefined}
              onChange={(event) => form.setConsent(event.target.checked)}
            />
            <label htmlFor={consentId} className="text-sm" style={LABEL_STYLE}>
              {definition.consent.text}
            </label>
          </div>
          {consentError && (
            <p id={`${consentId}-error`} className="mt-1 text-sm" style={ERROR_STYLE}>
              {t(consentError)}
            </p>
          )}
        </div>
      )}
      <div style={HONEYPOT_STYLE} aria-hidden="true">
        <label htmlFor={fieldId('hp')}>{t(ps.form.honeypot)}</label>
        <input
          id={fieldId('hp')}
          type="text"
          name="website"
          tabIndex={-1}
          autoComplete="off"
          value={form.hp}
          onChange={(event) => form.setHp(event.target.value)}
        />
      </div>
      {definition.captcha && !editing && (
        <CaptchaWidget
          provider={definition.captcha.provider}
          siteKey={definition.captcha.site_key}
          round={form.captchaRound}
          lang={locale}
          onToken={form.setCaptcha}
        />
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={sending || editing}
          className="rounded-md px-5 py-2 font-medium disabled:opacity-60"
          style={BUTTON_STYLE}
        >
          {sending ? t(ps.form.sending) : submitLabel}
        </button>
        {editing && (
          <span className="text-sm" style={HELP_STYLE}>
            {t(ps.block.editor_note)}
          </span>
        )}
      </div>
    </form>
  );
}
