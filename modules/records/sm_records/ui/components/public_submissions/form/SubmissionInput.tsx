/**
 * One input of a `RecordForm`, per submittable field type (#101, design §8).
 *
 * Plain elements styled with pagebuilder's `--pb-*` tokens, so a form reads
 * as part of the site rather than the admin console. The admin field editors
 * (`components/fields/*`) are not reused: they assume a session (the relation
 * and media pickers) and the console's chrome.
 *
 * Accessibility: every input has a `<label>`, a required one is marked
 * `aria-required` and says so in text, help and the error are tied to it with
 * `aria-describedby`, and a field in error is `aria-invalid`. A `pattern`
 * constraint is deliberately not copied to the browser: JavaScript and the
 * server's Python read some patterns differently, and the server decides.
 */

import type { CSSProperties, ReactNode } from 'react';
import { keys, useT } from '../../../utils/i18n';
import type { FormValue } from '../../../utils/submission-values';
import type { SubmissionField } from '../../../utils/submissions-form-api';

export const INPUT_CLASS =
  'w-full rounded-md border bg-transparent px-3 py-2 focus:outline-none focus:ring-2 focus:ring-[var(--pb-accent,#2563eb)]';
export const INPUT_STYLE: CSSProperties = {
  borderColor: 'var(--border, #d4d4d8)',
  color: 'var(--pb-body-color)',
};
export const LABEL_STYLE: CSSProperties = { color: 'var(--pb-heading-color)' };
export const HELP_STYLE: CSSProperties = { color: 'var(--pb-body-color)', opacity: 0.75 };
export const ERROR_STYLE: CSSProperties = { color: 'var(--pb-error-color, #b91c1c)' };

const INPUT_TYPES: Record<string, string> = {
  text: 'text',
  email: 'email',
  url: 'url',
  number: 'number',
  integer: 'number',
  date: 'date',
  datetime: 'datetime-local',
};

const AUTOCOMPLETE: Record<string, string> = { email: 'email', url: 'url' };

function num(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined;
}

type Props = {
  field: SubmissionField;
  id: string;
  label: string;
  help: string | null;
  value: FormValue;
  error: string | null;
  disabled: boolean;
  onChange: (value: FormValue) => void;
};

function Described({
  id,
  help,
  error,
  children,
}: {
  id: string;
  help: string | null;
  error: string | null;
  children: ReactNode;
}) {
  return (
    <>
      {children}
      {help && (
        <p id={`${id}-help`} className="mt-1 text-sm" style={HELP_STYLE}>
          {help}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-sm" style={ERROR_STYLE}>
          {error}
        </p>
      )}
    </>
  );
}

export function SubmissionInput({
  field,
  id,
  label,
  help,
  value,
  error,
  disabled,
  onChange,
}: Props) {
  const { t } = useT();
  const describedBy =
    [help ? `${id}-help` : null, error ? `${id}-error` : null].filter(Boolean).join(' ') ||
    undefined;
  const aria = {
    'aria-invalid': error ? true : undefined,
    'aria-describedby': describedBy,
    'aria-required': field.required || undefined,
  } as const;
  const marker = field.required ? (
    <span aria-hidden="true"> *</span>
  ) : (
    <span className="text-sm font-normal" style={HELP_STYLE}>
      {' '}
      {t(keys.records.public_submissions.form.optional)}
    </span>
  );
  const constraints = field.constraints ?? {};

  if (field.type === 'boolean') {
    return (
      <div data-testid={`records-form-field-${field.key}`}>
        <div className="flex items-start gap-2">
          <input
            id={id}
            type="checkbox"
            className="mt-1 h-4 w-4"
            checked={value === true}
            disabled={disabled}
            onChange={(event) => onChange(event.target.checked)}
            {...aria}
          />
          <label htmlFor={id} className="text-sm" style={LABEL_STYLE}>
            {label}
            {marker}
          </label>
        </div>
        <Described id={id} help={help} error={error}>
          {null}
        </Described>
      </div>
    );
  }

  if (field.type === 'multiselect') {
    const chosen = Array.isArray(value) ? value : [];
    return (
      <fieldset data-testid={`records-form-field-${field.key}`} aria-describedby={describedBy}>
        <legend className="mb-1 block text-sm font-medium" style={LABEL_STYLE}>
          {label}
          {marker}
        </legend>
        <Described id={id} help={help} error={error}>
          <div className="flex flex-col gap-1">
            {field.choices.map((choice, index) => (
              <label key={choice.value} className="flex items-center gap-2 text-sm">
                <input
                  id={index === 0 ? id : `${id}-${index}`}
                  type="checkbox"
                  checked={chosen.includes(choice.value)}
                  disabled={disabled}
                  onChange={(event) =>
                    onChange(
                      event.target.checked
                        ? [...chosen, choice.value]
                        : chosen.filter((item) => item !== choice.value),
                    )
                  }
                />
                <span style={LABEL_STYLE}>{choice.label}</span>
              </label>
            ))}
          </div>
        </Described>
      </fieldset>
    );
  }

  const text = typeof value === 'string' ? value : '';
  let control: ReactNode;
  if (field.type === 'longtext') {
    control = (
      <textarea
        id={id}
        rows={5}
        value={text}
        disabled={disabled}
        maxLength={num(constraints.max_length)}
        minLength={num(constraints.min_length)}
        className={INPUT_CLASS}
        style={INPUT_STYLE}
        onChange={(event) => onChange(event.target.value)}
        {...aria}
      />
    );
  } else if (field.type === 'select') {
    control = (
      <select
        id={id}
        value={text}
        disabled={disabled}
        className={INPUT_CLASS}
        style={INPUT_STYLE}
        onChange={(event) => onChange(event.target.value)}
        {...aria}
      >
        <option value="">{t(keys.records.public_submissions.form.choose)}</option>
        {field.choices.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
    );
  } else {
    control = (
      <input
        id={id}
        type={INPUT_TYPES[field.type] ?? 'text'}
        value={text}
        disabled={disabled}
        autoComplete={AUTOCOMPLETE[field.type]}
        step={field.type === 'integer' ? 1 : field.type === 'number' ? 'any' : undefined}
        min={num(constraints.min)}
        max={num(constraints.max)}
        maxLength={num(constraints.max_length)}
        minLength={num(constraints.min_length)}
        className={INPUT_CLASS}
        style={INPUT_STYLE}
        onChange={(event) => onChange(event.target.value)}
        {...aria}
      />
    );
  }
  return (
    <div data-testid={`records-form-field-${field.key}`}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium" style={LABEL_STYLE}>
        {label}
        {marker}
      </label>
      <Described id={id} help={help} error={error}>
        {control}
      </Described>
    </div>
  );
}
