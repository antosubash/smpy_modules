/** One `field / condition / value` row of the segment editor. */

import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useId } from 'react';

import { keys, useT } from '../../utils/i18n';
import { emptyRule, valueInput } from '../../utils/rules';
import type { ListField, Rule, RuleOp } from '../../utils/types';

const copy = keys.newsletter.segments;

/** Every operator's label, as `keys` leaves rather than a template literal. */
export const OP_LABELS: Record<RuleOp, string> = {
  is: copy.ops.is,
  is_not: copy.ops.is_not,
  any: copy.ops.any,
  all: copy.ops.all,
  none: copy.ops.none,
  contains: copy.ops.contains,
  starts_with: copy.ops.starts_with,
  gt: copy.ops.gt,
  gte: copy.ops.gte,
  lt: copy.ops.lt,
  lte: copy.ops.lte,
  before: copy.ops.before,
  since: copy.ops.since,
};

/** The API's cap on one rule value (`segments.rules.MAX_VALUE_LEN`); more is a 422. */
export const MAX_VALUE_LEN = 200;

/** The synthetic signup-time field is named by the catalogue, not by the server's English label. */
export const SIGNUP_FIELD = 'created_at';

interface Props {
  rule: Rule;
  fields: ListField[];
  onChange: (r: Rule) => void;
  onRemove: () => void;
  disabled: boolean;
  /** The server named this row in a 422. */
  invalid?: boolean;
}

export function RuleRow({ rule, fields, onChange, onRemove, disabled, invalid }: Props) {
  const { t } = useT();
  const id = useId();
  const field = fields.find((f) => f.key === rule.field);
  const input = field ? valueInput(field, rule.op) : 'text';
  const label = (f: ListField) => (f.key === SIGNUP_FIELD ? t(copy.signup_field) : f.label);

  const changeField = (key: string) => {
    const next = fields.find((f) => f.key === key);
    if (next) onChange(emptyRule(next));
  };
  const changeOp = (op: RuleOp) => {
    const next = field ? valueInput(field, op) : 'text';
    const wasList = Array.isArray(rule.value);
    onChange({
      ...rule,
      op,
      value: next === 'choices' ? (wasList ? rule.value : []) : wasList ? '' : rule.value,
    });
  };
  const chosen = Array.isArray(rule.value) ? rule.value : [];
  const toggle = (value: string, on: boolean) =>
    onChange({
      ...rule,
      value: on ? [...chosen, value] : chosen.filter((v) => v !== value),
    });
  const aria = { 'aria-invalid': invalid || undefined };

  return (
    <div
      data-rule-row=""
      data-invalid={invalid ? 'true' : 'false'}
      className={`flex flex-wrap items-start gap-2 rounded-md border p-2 ${
        invalid ? 'border-destructive' : 'border-transparent'
      }`}
    >
      <NativeSelect
        aria-label={t(copy.field)}
        disabled={disabled}
        value={rule.field}
        onChange={(e) => changeField(e.target.value)}
        {...aria}
      >
        {!field && <option value={rule.field}>{rule.field}</option>}
        {fields.map((f) => (
          <option key={f.key} value={f.key}>
            {label(f)}
          </option>
        ))}
      </NativeSelect>
      <NativeSelect
        aria-label={t(copy.op)}
        disabled={disabled || !field}
        value={rule.op}
        onChange={(e) => changeOp(e.target.value as RuleOp)}
        {...aria}
      >
        {(field?.ops ?? [rule.op]).map((op) => (
          <option key={op} value={op}>
            {t(OP_LABELS[op])}
          </option>
        ))}
      </NativeSelect>

      {input === 'choices' && field && (
        <fieldset aria-label={t(copy.value)} className="flex flex-wrap gap-3 py-1">
          {field.choices.map((c) => (
            <div key={c.value} className="flex items-center gap-1.5 text-sm">
              <Checkbox
                id={`${id}-${c.value}`}
                disabled={disabled}
                checked={chosen.includes(c.value)}
                onCheckedChange={(on) => toggle(c.value, on === true)}
              />
              <Label htmlFor={`${id}-${c.value}`}>{c.label}</Label>
            </div>
          ))}
        </fieldset>
      )}
      {(input === 'choice' || input === 'boolean') && (
        <NativeSelect
          aria-label={t(copy.value)}
          disabled={disabled}
          value={typeof rule.value === 'string' ? rule.value : ''}
          onChange={(e) => onChange({ ...rule, value: e.target.value })}
          {...aria}
        >
          <option value="" disabled>
            {t(copy.pick)}
          </option>
          {input === 'boolean' ? (
            <>
              <option value="true">{t(copy.bool.true)}</option>
              <option value="false">{t(copy.bool.false)}</option>
            </>
          ) : (
            field?.choices.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))
          )}
        </NativeSelect>
      )}
      {(input === 'text' || input === 'number' || input === 'date') && (
        <Input
          id={`${id}-value`}
          className="w-48"
          aria-label={t(copy.value)}
          type={input === 'text' ? 'text' : input}
          step={input === 'number' ? 'any' : undefined}
          maxLength={input === 'text' ? MAX_VALUE_LEN : undefined}
          disabled={disabled}
          value={typeof rule.value === 'string' ? rule.value : ''}
          onChange={(e) => onChange({ ...rule, value: e.target.value })}
          {...aria}
        />
      )}

      <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={onRemove}>
        {t(copy.remove_rule)}
      </Button>
    </div>
  );
}
