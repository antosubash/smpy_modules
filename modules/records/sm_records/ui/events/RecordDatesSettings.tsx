/** The settings of the `records:dates` source: up to five mappings, each a record type, an
 *  indexed date or date-time field of it and, optionally, an end field of the same kind. The
 *  choices come from records' own type list; the server checks them again on save. */
import type { SourceSettingsProps } from '@simple-module-py/events';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { useEffect, useState } from 'react';
import { listTypes } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import type { FieldDef, TypeRead } from '../utils/types';

const MAX_MAPPINGS = 5;
const DATE_KINDS = ['date', 'datetime'];

type Hidden = { hidden: true; token: string };
type Mapping = {
  type_key: string;
  field: string;
  end_field?: string | null;
  duration_minutes?: number;
  color?: string | null;
};

const dateFields = (type: TypeRead | undefined): FieldDef[] =>
  (type?.fields ?? []).filter((f) => f.indexed && DATE_KINDS.includes(f.type));

const isHidden = (m: Mapping | Hidden): m is Hidden => 'hidden' in m && m.hidden === true;

const mappingsOf = (settings: SourceSettingsProps['settings']): (Mapping | Hidden)[] => {
  const raw = settings.mappings;
  return Array.isArray(raw) && raw.length > 0
    ? (raw as (Mapping | Hidden)[])
    : [{ type_key: '', field: '' }];
};

/** The server's short code for a problem, as a sentence in the reader's language. */
const CODE_KEYS = {
  field_missing: 'error_field_missing',
  field_not_date: 'error_field_not_date',
  type_unavailable: 'error_type_unavailable',
  end_same: 'error_end_same',
  end_kind: 'error_end_kind',
} as const;

export default function RecordDatesSettings({
  settings,
  onChange,
  errors,
  codes,
}: SourceSettingsProps) {
  const { t } = useT();
  const copy = keys.records.events.settings;
  const [types, setTypes] = useState<TypeRead[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    listTypes()
      .then(({ items }) => alive && setTypes(items))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  const mappings = mappingsOf(settings);
  const update = (index: number, patch: Partial<Mapping>) =>
    onChange({
      ...settings,
      mappings: mappings.map((m, i) => (i === index && !isHidden(m) ? { ...m, ...patch } : m)),
    });
  const remove = (index: number) =>
    onChange({ ...settings, mappings: mappings.filter((_, i) => i !== index) });
  const add = () => onChange({ ...settings, mappings: [...mappings, { type_key: '', field: '' }] });

  return (
    <div className="grid gap-4">
      <p className="text-sm text-muted-foreground">{t(copy.hint)}</p>
      {failed ? (
        <p role="alert" className="text-destructive">
          {t(copy.load_failed)}
        </p>
      ) : null}
      {mappings.map((mapping, index) => {
        const id = `records-dates-${index}`;
        if (isHidden(mapping)) {
          return (
            <fieldset
              key={`${id}-${mapping.token}`}
              className="grid gap-2 rounded-md border border-dashed p-3"
              data-testid="records-mapping-hidden"
            >
              <legend className="px-1 text-sm font-medium">
                {t(copy.mapping, { n: index + 1 })}
              </legend>
              <p className="text-sm text-muted-foreground">{t(copy.hidden)}</p>
            </fieldset>
          );
        }
        const type = types?.find((candidate) => candidate.key === mapping.type_key);
        const fields = dateFields(type);
        const start = fields.find((f) => f.key === mapping.field);
        const ends = fields.filter((f) => f.key !== mapping.field && f.type === start?.type);
        const error = (name: string) => {
          const path = `mappings.${index}.${name}`;
          const known = CODE_KEYS[codes?.[path] as keyof typeof CODE_KEYS];
          return known ? t(copy[known]) : errors[path];
        };
        // A stored value the type no longer offers stays visible (and fixable), never blank.
        const withStale = (
          choices: { value: string; label: string }[],
          value: string | null | undefined,
        ) =>
          value && !choices.some((c) => c.value === value)
            ? [{ value, label: t(copy.field_gone, { field: value }) }, ...choices]
            : choices;
        const select = (
          name: 'type_key' | 'field' | 'end_field',
          suffix: string,
          label: string,
          value: string,
          choices: { value: string; label: string }[],
          empty: string,
          patch: (v: string) => Partial<Mapping>,
        ) => (
          <div className="grid gap-2">
            <Label htmlFor={`${id}-${suffix}`}>{label}</Label>
            <NativeSelect
              id={`${id}-${suffix}`}
              value={value}
              aria-invalid={error(name) ? true : undefined}
              aria-describedby={error(name) ? `${id}-${suffix}-error` : undefined}
              onChange={(e) => update(index, patch(e.target.value))}
            >
              <NativeSelectOption value="">{empty}</NativeSelectOption>
              {choices.map((c) => (
                <NativeSelectOption key={c.value} value={c.value}>
                  {c.label}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <FieldError id={`${id}-${suffix}-error`}>{error(name)}</FieldError>
          </div>
        );
        return (
          <fieldset
            key={`${id}-${mapping.type_key}`}
            className="grid gap-3 rounded-md border p-3"
            data-testid="records-mapping"
          >
            <legend className="px-1 text-sm font-medium">
              {t(copy.mapping, { n: index + 1 })}
            </legend>
            {select(
              'type_key',
              'type',
              t(copy.type),
              mapping.type_key,
              withStale(
                (types ?? [])
                  .filter(
                    (candidate) =>
                      dateFields(candidate).length > 0 || candidate.key === mapping.type_key,
                  )
                  .map((candidate) => ({ value: candidate.key, label: candidate.label })),
                types === null ? null : mapping.type_key,
              ),
              t(copy.choose),
              (value) => ({ type_key: value, field: '', end_field: null }),
            )}
            {select(
              'field',
              'field',
              t(copy.field),
              mapping.field,
              withStale(
                fields.map((f) => ({ value: f.key, label: f.label })),
                types === null ? null : mapping.field,
              ),
              t(copy.choose),
              (value) => ({ field: value, end_field: null }),
            )}
            {select(
              'end_field',
              'end',
              t(copy.end),
              mapping.end_field ?? '',
              withStale(
                ends.map((f) => ({ value: f.key, label: f.label })),
                types === null ? null : mapping.end_field,
              ),
              t(copy.none),
              (value) => ({ end_field: value || null }),
            )}
            {start?.type === 'datetime' ? (
              <div className="grid gap-2">
                <Label htmlFor={`${id}-duration`}>{t(copy.duration)}</Label>
                <Input
                  id={`${id}-duration`}
                  type="number"
                  min={1}
                  max={1440}
                  value={mapping.duration_minutes ?? 60}
                  onChange={(e) => update(index, { duration_minutes: Number(e.target.value) })}
                />
              </div>
            ) : null}
            <div className="grid gap-2">
              <Label htmlFor={`${id}-color`}>{t(copy.color)}</Label>
              <Input
                id={`${id}-color`}
                value={mapping.color ?? ''}
                placeholder="#2563eb"
                maxLength={7}
                aria-invalid={error('color') ? true : undefined}
                onChange={(e) => update(index, { color: e.target.value.toLowerCase() || null })}
              />
              <FieldError id={`${id}-color-error`}>{error('color')}</FieldError>
            </div>
            {mappings.length > 1 ? (
              <Button type="button" variant="outline" size="sm" onClick={() => remove(index)}>
                {t(copy.remove)}
              </Button>
            ) : null}
          </fieldset>
        );
      })}
      <Button
        type="button"
        variant="outline"
        disabled={mappings.length >= MAX_MAPPINGS}
        onClick={add}
      >
        {t(copy.add)}
      </Button>
    </div>
  );
}
