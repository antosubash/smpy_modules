import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { type FormEvent, useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import { type SchemaField, schemaToFields } from '../../utils/schemaFields';
import type { JsonSchema } from '../../utils/types-prompts';

type Values = Record<string, string | boolean>;
type Data = Record<string, unknown>;

type Props = {
  /** The prompt's `output_schema`; `null` is a free-text prompt. */
  schema: JsonSchema | null;
  /** The value to start from: the reviewed one, else the model's. */
  initial: Data | null;
  initialText: string | null;
  busy: boolean;
  onSubmit: (data: Data) => void;
  onCancel: () => void;
};

const initialValue = (field: SchemaField, from: unknown): string | boolean => {
  if (field.type === 'boolean') return from === true;
  if (Array.isArray(from)) return from.join('\n');
  return from === undefined || from === null ? '' : String(from);
};

/** The value of one field, or the catalogue key of what is wrong with it. */
function read(field: SchemaField, raw: string | boolean): { value?: unknown; error?: string } {
  if (field.type === 'boolean') return { value: raw === true };
  const text = String(raw);
  if (field.type === 'string_list') {
    const lines = text.split('\n').filter((line) => line.trim() !== '');
    return lines.length || field.required ? { value: lines } : {};
  }
  if (text === '') return field.required ? { error: keys.images.review.form.required } : {};
  if (field.type === 'string') return { value: text };
  const n = Number(text);
  if (!Number.isFinite(n)) return { error: keys.images.review.form.number_invalid };
  if (field.type === 'integer' && !Number.isInteger(n)) {
    return { error: keys.images.review.form.integer_invalid };
  }
  return { value: n };
}

/**
 * The correction form, generated from the prompt's output schema: one input
 * per field when the field builder can express the schema exactly
 * (`schemaToFields`), else the corrected JSON itself; a free-text prompt gets
 * a text box. The server checks the result against the same schema again.
 */
export function CorrectionForm({ schema, initial, initialText, busy, onSubmit, onCancel }: Props) {
  const { t } = useT();
  const fields = schema === null ? null : schemaToFields(schema);
  const [values, setValues] = useState<Values>(() =>
    Object.fromEntries((fields ?? []).map((f) => [f.name, initialValue(f, initial?.[f.name])])),
  );
  const [text, setText] = useState(() =>
    schema === null
      ? typeof initial?.text === 'string'
        ? initial.text
        : (initialText ?? '')
      : JSON.stringify(initial ?? {}, null, 2),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (schema === null) return onSubmit({ text });
    if (fields === null) {
      try {
        const parsed: unknown = JSON.parse(text);
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
          return setErrors({ '': keys.images.review.form.json_object });
        }
        return onSubmit(parsed as Data);
      } catch {
        return setErrors({ '': keys.images.review.form.json_invalid });
      }
    }
    const data: Data = {};
    const found: Record<string, string> = {};
    for (const field of fields) {
      const { value, error } = read(field, values[field.name]);
      if (error) found[field.name] = error;
      else if (value !== undefined) data[field.name] = value;
    }
    setErrors(found);
    if (Object.keys(found).length === 0) onSubmit(data);
  };

  const set = (name: string, value: string | boolean) =>
    setValues((v) => ({ ...v, [name]: value }));

  return (
    <form onSubmit={submit} className="space-y-3" data-testid="images-review-form">
      {schema === null || fields === null ? (
        <div className="grid gap-2">
          <Label htmlFor="images-review-text">
            {t(schema === null ? keys.images.review.form.text : keys.images.review.form.json)}
          </Label>
          <Textarea
            id="images-review-text"
            data-testid="images-review-text"
            rows={schema === null ? 4 : 10}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          {errors[''] && <p className="text-sm text-destructive">{t(errors[''])}</p>}
        </div>
      ) : (
        fields.map((field) => (
          <div key={field.name} className="grid gap-1">
            <Label htmlFor={`images-review-field-${field.name}`}>
              {field.name}
              {field.required ? ' *' : ''}
            </Label>
            {field.description && (
              <p className="text-xs text-muted-foreground">{field.description}</p>
            )}
            {field.type === 'boolean' ? (
              <input
                id={`images-review-field-${field.name}`}
                data-testid={`images-review-field-${field.name}`}
                type="checkbox"
                className="size-4"
                checked={values[field.name] === true}
                onChange={(e) => set(field.name, e.target.checked)}
              />
            ) : field.type === 'string' && field.choices.length > 0 ? (
              <NativeSelect
                id={`images-review-field-${field.name}`}
                data-testid={`images-review-field-${field.name}`}
                value={String(values[field.name])}
                onChange={(e) => set(field.name, e.target.value)}
              >
                <option value="">{t(keys.images.review.form.choose)}</option>
                {field.choices.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </NativeSelect>
            ) : field.type === 'string_list' ? (
              <Textarea
                id={`images-review-field-${field.name}`}
                data-testid={`images-review-field-${field.name}`}
                rows={3}
                placeholder={t(keys.images.review.form.list_hint)}
                value={String(values[field.name])}
                onChange={(e) => set(field.name, e.target.value)}
              />
            ) : (
              <Input
                id={`images-review-field-${field.name}`}
                data-testid={`images-review-field-${field.name}`}
                value={String(values[field.name])}
                inputMode={field.type === 'string' ? undefined : 'decimal'}
                onChange={(e) => set(field.name, e.target.value)}
              />
            )}
            {errors[field.name] && (
              <p className="text-sm text-destructive">{t(errors[field.name])}</p>
            )}
          </div>
        ))
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy} data-testid="images-review-save">
          {t(keys.images.review.save)}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={onCancel}
          data-testid="images-review-cancel"
        >
          {t(keys.images.review.cancel)}
        </Button>
      </div>
    </form>
  );
}
