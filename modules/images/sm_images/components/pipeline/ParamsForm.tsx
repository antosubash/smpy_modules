import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { JsonSchema } from '../../utils/types';

type Params = Record<string, unknown>;

/** Names that would reach the prototype if used as a key. */
const UNSAFE = new Set(['__proto__', 'constructor', 'prototype']);

/** The one non-null branch of a pydantic `Optional[...]`, else the schema. */
function resolve(schema: JsonSchema): JsonSchema {
  const branches = (schema.anyOf ?? []).filter((b) => b.type !== 'null');
  return branches.length === 1 ? { ...schema, ...branches[0] } : schema;
}

type Kind = 'string' | 'number' | 'integer' | 'boolean' | 'enum' | 'strings' | 'json';

export function kindOf(schema: JsonSchema): Kind {
  const s = resolve(schema);
  if (s.enum) return 'enum';
  if (s.type === 'array' && s.items?.type === 'string' && !s.items.enum) return 'strings';
  if (s.type === 'string' || s.type === 'number' || s.type === 'integer' || s.type === 'boolean')
    return s.type;
  return 'json';
}

/** A JSON value edited as text. An unparseable draft is held locally and
 *  flagged; only valid JSON reaches the parent. */
function JsonField({
  id,
  value,
  disabled,
  onChange,
}: {
  id: string;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const { t } = useT();
  const [text, setText] = useState(value === undefined ? '' : JSON.stringify(value, null, 2));
  const [bad, setBad] = useState(false);
  return (
    <>
      <Textarea
        id={id}
        value={text}
        disabled={disabled}
        aria-invalid={bad}
        className="font-mono text-xs"
        onChange={(e) => {
          const next = e.target.value;
          setText(next);
          if (next.trim() === '') {
            setBad(false);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(next));
            setBad(false);
          } catch {
            setBad(true);
          }
        }}
      />
      {bad && <p className="text-xs text-destructive">{t(keys.images.pipeline.invalid_json)}</p>}
    </>
  );
}

function Field({
  id,
  schema,
  value,
  disabled,
  onChange,
}: {
  id: string;
  schema: JsonSchema;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const s = resolve(schema);
  const kind = kindOf(schema);
  const shown = value === undefined ? s.default : value;
  switch (kind) {
    case 'boolean':
      return (
        <input
          id={id}
          type="checkbox"
          checked={shown === true}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
      );
    case 'enum':
      return (
        <select
          id={id}
          value={shown === undefined || shown === null ? '' : String(shown)}
          disabled={disabled}
          className="h-9 rounded-md border bg-background px-2 text-sm"
          onChange={(e) => {
            const picked = (s.enum ?? []).find((o) => String(o) === e.target.value);
            onChange(picked);
          }}
        >
          {shown === undefined && <option value="" />}
          {(s.enum ?? []).map((o) => (
            <option key={String(o)} value={String(o)}>
              {String(o)}
            </option>
          ))}
        </select>
      );
    case 'number':
    case 'integer':
      return (
        <Input
          id={id}
          type="number"
          step={kind === 'integer' ? 1 : 'any'}
          value={shown === undefined || shown === null ? '' : String(shown)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
        />
      );
    case 'string':
      return (
        <Input
          id={id}
          value={shown === undefined || shown === null ? '' : String(shown)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value === '' ? undefined : e.target.value)}
        />
      );
    case 'strings':
      return (
        <Textarea
          id={id}
          rows={3}
          value={Array.isArray(shown) ? shown.join('\n') : ''}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value === '' ? [] : e.target.value.split('\n'))}
        />
      );
    default:
      return <JsonField id={id} value={shown} disabled={disabled} onChange={onChange} />;
  }
}

/**
 * A form for one step's `params_schema` (a pydantic JSON Schema): string,
 * number, integer, boolean, enum and arrays of strings get a control; anything
 * else (nested objects, arrays of objects, unions) a JSON textarea. A cleared
 * field drops its key, so the server's default applies.
 */
export function ParamsForm({
  stepId,
  schema,
  value,
  disabled,
  onChange,
}: {
  stepId: string;
  schema: JsonSchema;
  value: Params;
  disabled: boolean;
  onChange: (next: Params) => void;
}) {
  const fields = Object.entries(schema.properties ?? {}).filter(([name]) => !UNSAFE.has(name));
  if (fields.length === 0) return null;
  return (
    <div className="grid gap-3 sm:grid-cols-2" data-testid={`images-params-${stepId}`}>
      {fields.map(([name, prop]) => {
        const id = `images-param-${stepId}-${name}`;
        const next = (v: unknown) => {
          const copy = { ...value };
          if (v === undefined) delete copy[name];
          else copy[name] = v;
          onChange(copy);
        };
        return (
          <div key={name} className="grid gap-1.5">
            <Label htmlFor={id}>{prop.title ?? name}</Label>
            <Field id={id} schema={prop} value={value[name]} disabled={disabled} onChange={next} />
            {prop.description && (
              <p className="text-xs text-muted-foreground">{prop.description}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
