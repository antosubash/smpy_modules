/** The block's "Number of events" field: a whole number from 1 to the maximum. Puck's own number
 *  field takes any number and would let 2.7 or 99 through to be clamped silently at render; this one
 *  says what it refuses, in words, and hands the value on exactly as typed. */

import { type CustomField, FieldLabel } from '@puckeditor/core';

import { keys, useT } from '../utils/i18n';
import { countProblem, UPCOMING_MAX, UPCOMING_MIN } from './limits';

const copy = keys.events.blocks.upcoming;

function CountInput(props: {
  label: string;
  id: string;
  value: unknown;
  onChange: (value: number | undefined) => void;
  readOnly?: boolean;
}) {
  const { t } = useT();
  const problem = countProblem(props.value);
  const messageId = `${props.id}-error`;
  return (
    <FieldLabel label={props.label}>
      <input
        id={props.id}
        type="number"
        step={1}
        min={UPCOMING_MIN}
        max={UPCOMING_MAX}
        readOnly={props.readOnly}
        value={typeof props.value === 'number' && !Number.isNaN(props.value) ? props.value : ''}
        aria-invalid={problem ? true : undefined}
        aria-describedby={problem ? messageId : undefined}
        onChange={(e) => props.onChange(e.target.value === '' ? undefined : Number(e.target.value))}
        style={{ width: '100%', padding: 12, border: '1px solid var(--puck-color-grey-09)' }}
      />
      {problem ? (
        <p id={messageId} role="alert" data-count-error="" style={{ color: '#b91c1c', margin: 4 }}>
          {t(copy.count_invalid, { max: UPCOMING_MAX })}
        </p>
      ) : null}
    </FieldLabel>
  );
}

export function countField(label: string): CustomField<number> {
  return {
    type: 'custom',
    label,
    render: ({ value, onChange, id, readOnly, field }) => (
      <CountInput
        label={field.label ?? label}
        id={id}
        value={value}
        readOnly={readOnly}
        onChange={(next) => onChange(next as number)}
      />
    ),
  };
}
