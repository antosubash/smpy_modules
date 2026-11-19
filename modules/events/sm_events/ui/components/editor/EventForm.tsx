import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import type { ReactNode } from 'react';
import type { FormState } from '../../utils/event-form';
import { fieldErrorId, invalidProps } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import type { Category } from '../../utils/types';
import { ATTENDANCE_MODES, type AttendanceMode } from '../../utils/types-events';
import { categoryName } from '../events/EventFilters';
import { TimesFields } from './TimesFields';

type Text =
  | 'venue_name'
  | 'address'
  | 'online_url'
  | 'latitude'
  | 'longitude'
  | 'organiser'
  | 'image'
  | 'registration_url';

/** The fields that are not language-specific: when, where, category and flags. */
export function EventForm({
  form,
  errors,
  disabled,
  categories,
  locales,
  onChange,
  onEdit,
  typeSection,
}: {
  form: FormState;
  errors: Record<string, string>;
  disabled: boolean;
  categories: Category[];
  /** Content languages, the console's first, for category names. */
  locales: readonly string[];
  onChange: (patch: Partial<FormState>) => void;
  onEdit: (path: string) => void;
  /** The type picker and the plugin's section, when the page has types to offer. */
  typeSection?: ReactNode;
}) {
  const { t } = useT();
  const copy = keys.events.editor;
  const text = (
    name: Text,
    label: string,
    extra: { type?: string; multiline?: boolean; max: number },
  ): ReactNode => {
    const id = `event-${name.replace('_', '-')}`;
    const Control = extra.multiline ? Textarea : Input;
    return (
      <div className="grid gap-2">
        <Label htmlFor={id}>{label}</Label>
        <Control
          id={id}
          type={extra.multiline ? undefined : (extra.type ?? 'text')}
          step={extra.type === 'number' ? 'any' : undefined}
          maxLength={extra.type === 'number' ? undefined : extra.max}
          disabled={disabled}
          value={form[name]}
          {...invalidProps(id, errors[name])}
          onChange={(e) => {
            onChange({ [name]: e.target.value });
            onEdit(name);
          }}
        />
        <FieldError id={fieldErrorId(id)}>{errors[name]}</FieldError>
      </div>
    );
  };
  return (
    <div className="grid gap-6">
      {typeSection}
      <TimesFields
        form={form}
        errors={errors}
        disabled={disabled}
        onChange={(next) => onChange(next)}
        onEdit={onEdit}
      />
      <fieldset className="grid gap-4" disabled={disabled}>
        <legend className="mb-2 text-sm font-medium">{t(copy.where)}</legend>
        {text('venue_name', t(copy.venue), { max: 200 })}
        {text('address', t(copy.address), { multiline: true, max: 500 })}
        <div className="grid gap-2">
          <Label htmlFor="event-attendance">{t(copy.attendance)}</Label>
          <NativeSelect
            id="event-attendance"
            value={form.attendance_mode}
            onChange={(e) => onChange({ attendance_mode: e.target.value as AttendanceMode })}
          >
            {ATTENDANCE_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {t(copy[`attendance_${mode}`])}
              </option>
            ))}
          </NativeSelect>
        </div>
        {text('online_url', t(copy.online_url), { type: 'url', max: 2048 })}
        <div className="grid gap-4 sm:grid-cols-2">
          {text('latitude', t(copy.latitude), { type: 'number', max: 0 })}
          {text('longitude', t(copy.longitude), { type: 'number', max: 0 })}
        </div>
      </fieldset>
      <fieldset className="grid gap-4" disabled={disabled}>
        <legend className="mb-2 text-sm font-medium">{t(copy.more)}</legend>
        <div className="grid gap-2">
          <Label htmlFor="event-category">{t(copy.category)}</Label>
          <NativeSelect
            id="event-category"
            value={form.category_id}
            {...invalidProps('event-category', errors.category_id)}
            onChange={(e) => {
              onChange({ category_id: e.target.value });
              onEdit('category_id');
            }}
          >
            <option value="">{t(copy.no_category)}</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {categoryName(c, locales, t(keys.events.list.no_category_name))}
              </option>
            ))}
          </NativeSelect>
          <FieldError id={fieldErrorId('event-category')}>{errors.category_id}</FieldError>
        </div>
        {text('organiser', t(copy.organiser), { max: 200 })}
        {text('image', t(copy.image), { max: 2048 })}
        <p className="-mt-4 text-xs text-muted-foreground">{t(copy.image_hint)}</p>
        {text('registration_url', t(copy.registration_url), { type: 'url', max: 2048 })}
        <div className="flex items-center gap-2">
          <Checkbox
            id="event-cancelled"
            checked={form.cancelled}
            onCheckedChange={(on) => onChange({ cancelled: on === true })}
          />
          <Label htmlFor="event-cancelled">{t(copy.cancelled)}</Label>
        </div>
      </fieldset>
    </div>
  );
}
