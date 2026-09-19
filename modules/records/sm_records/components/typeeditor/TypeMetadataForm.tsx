import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { Switch } from '@simple-module-py/ui/components/ui/switch';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';

import type { ValidationError } from '../../utils/types';
import { fieldMessage } from './errors';
import { RolesMultiSelect } from './RolesMultiSelect';
import type { EditableField, TypeMetadataValues } from './types';

const ID = {
  key: 'type-editor-key',
  label: 'type-editor-label',
  labelPlural: 'type-editor-label-plural',
  description: 'type-editor-description',
  icon: 'type-editor-icon',
  isPublic: 'type-editor-is-public',
  displayField: 'type-editor-display-field',
  slugField: 'type-editor-slug-field',
};

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-sm text-destructive">{message}</p>;
}

/**
 * The type's own labels, visibility and field pointers — everything
 * `update_type` keeps editable even on a `fields_locked` type (design §16).
 * `displayField`/`slugField` are the exception: they are locked with
 * `fields` because `display_title`/`slug` are denormalised from them onto
 * every existing record, so `fieldsLocked` disables those two selects here
 * even though the rest of the form stays live.
 */
export function TypeMetadataForm({
  isNew,
  fieldsLocked,
  fields,
  roles,
  values,
  onChange,
  errors,
}: {
  isNew: boolean;
  fieldsLocked: boolean;
  fields: EditableField[];
  roles: string[];
  values: TypeMetadataValues;
  onChange: (patch: Partial<TypeMetadataValues>) => void;
  errors: ValidationError[];
}) {
  const { t } = useT();
  const none = t('records.type_editor.pointer_none', { defaultValue: 'None' });

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="grid gap-1.5">
        <Label htmlFor={ID.key}>{t('records.types.key', { defaultValue: 'Key' })}</Label>
        {isNew ? (
          <Input
            id={ID.key}
            value={values.key}
            onChange={(e) => onChange({ key: e.target.value })}
            aria-invalid={!!fieldMessage(errors, 'key')}
          />
        ) : (
          <>
            <Input id={ID.key} value={values.key} disabled readOnly />
            <p className="text-sm text-muted-foreground">
              {t('records.type_editor.key_immutable', {
                defaultValue: "The key can't be changed once the type is created.",
              })}
            </p>
          </>
        )}
        <FieldError message={fieldMessage(errors, 'key')} />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={ID.label}>{t('records.types.label', { defaultValue: 'Label' })}</Label>
        <Input
          id={ID.label}
          value={values.label}
          onChange={(e) => onChange({ label: e.target.value })}
          aria-invalid={!!fieldMessage(errors, 'label')}
        />
        <FieldError message={fieldMessage(errors, 'label')} />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={ID.labelPlural}>
          {t('records.types.label_plural', { defaultValue: 'Plural label' })}
        </Label>
        <Input
          id={ID.labelPlural}
          value={values.labelPlural}
          onChange={(e) => onChange({ labelPlural: e.target.value })}
          aria-invalid={!!fieldMessage(errors, 'label_plural')}
        />
        <FieldError message={fieldMessage(errors, 'label_plural')} />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={ID.icon}>{t('records.type_editor.icon', { defaultValue: 'Icon' })}</Label>
        <Input
          id={ID.icon}
          value={values.icon}
          onChange={(e) => onChange({ icon: e.target.value })}
          placeholder={t('records.type_editor.icon_placeholder', { defaultValue: 'database' })}
          aria-invalid={!!fieldMessage(errors, 'icon')}
        />
        <p className="text-sm text-muted-foreground">
          {t('records.type_editor.icon_help', {
            defaultValue: 'The name of a lucide-react icon, e.g. "database".',
          })}
        </p>
        <FieldError message={fieldMessage(errors, 'icon')} />
      </div>

      <div className="grid gap-1.5 sm:col-span-2">
        <Label htmlFor={ID.description}>
          {t('records.types.description', { defaultValue: 'Description' })}
        </Label>
        <Textarea
          id={ID.description}
          value={values.description}
          onChange={(e) => onChange({ description: e.target.value })}
          rows={3}
        />
        <FieldError message={fieldMessage(errors, 'description')} />
      </div>

      <div className="flex items-center gap-2 sm:col-span-2">
        <Switch
          id={ID.isPublic}
          checked={values.isPublic}
          onCheckedChange={(checked) => onChange({ isPublic: checked === true })}
        />
        <Label htmlFor={ID.isPublic} className="font-normal">
          {t('records.type_editor.is_public', { defaultValue: 'Public' })}
        </Label>
      </div>
      <p className="-mt-2 text-sm text-muted-foreground sm:col-span-2">
        {t('records.type_editor.is_public_help', {
          defaultValue:
            "Exposes a read-only public API for this type's published records (design §10).",
        })}
      </p>

      <div className="grid gap-1.5 sm:col-span-2">
        <Label>{t('records.type_editor.allowed_roles', { defaultValue: 'Allowed roles' })}</Label>
        <RolesMultiSelect
          idPrefix="type-editor-role"
          roles={roles}
          selected={values.allowedRoles}
          onChange={(next) => onChange({ allowedRoles: next })}
        />
        <p className="text-sm text-muted-foreground">
          {t('records.type_editor.allowed_roles_help', {
            defaultValue:
              'Leave empty to allow anyone holding "Manage record types". Selecting one or more roles narrows access to those roles as well.',
          })}
        </p>
        <FieldError message={fieldMessage(errors, 'allowed_roles')} />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={ID.displayField}>
          {t('records.type_editor.display_field', { defaultValue: 'Display field' })}
        </Label>
        <NativeSelect
          id={ID.displayField}
          value={values.displayField}
          disabled={fieldsLocked}
          onChange={(e) => onChange({ displayField: e.target.value })}
        >
          <NativeSelectOption value="">{none}</NativeSelectOption>
          {fields.map((f) => (
            <NativeSelectOption key={f.key} value={f.key}>
              {f.label} ({f.key})
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <FieldError message={fieldMessage(errors, 'display_field')} />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={ID.slugField}>
          {t('records.type_editor.slug_field', { defaultValue: 'Slug field' })}
        </Label>
        <NativeSelect
          id={ID.slugField}
          value={values.slugField}
          disabled={fieldsLocked}
          onChange={(e) => onChange({ slugField: e.target.value })}
        >
          <NativeSelectOption value="">{none}</NativeSelectOption>
          {fields.map((f) => (
            <NativeSelectOption key={f.key} value={f.key}>
              {f.label} ({f.key})
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <FieldError message={fieldMessage(errors, 'slug_field')} />
      </div>
    </div>
  );
}
