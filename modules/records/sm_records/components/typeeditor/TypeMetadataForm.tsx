import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { Switch } from '@simple-module-py/ui/components/ui/switch';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useEffect } from 'react';
import type { ValidationError } from '../../utils/types';
import { CollectionField } from './CollectionField';
import { fieldMessage } from './errors';
import { PublicField } from './PublicField';
import { RolesMultiSelect } from './RolesMultiSelect';
import { displayFieldAllowed, slugFieldAllowed } from './rules';
import type { EditableField, TypeMetadataValues } from './types';

const ID = {
  key: 'type-editor-key',
  label: 'type-editor-label',
  labelPlural: 'type-editor-label-plural',
  description: 'type-editor-description',
  icon: 'type-editor-icon',
  translatable: 'type-editor-translatable',
  displayField: 'type-editor-display-field',
  slugField: 'type-editor-slug-field',
};

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-sm text-destructive">{message}</p>;
}

/**
 * The type's own labels, visibility and field pointers. Phase 3 lifts the
 * Phase 1 lock (design §16): `displayField`/`slugField` are editable even on
 * a populated type now, same as `fields` — changing either is classified and
 * dry-run like any other schema write, since `display_title`/`slug` are
 * denormalised from them onto every existing record.
 */
export function TypeMetadataForm({
  isNew,
  fields,
  roles,
  values,
  onChange,
  errors,
  publicRoutePrefix,
  contentLocales,
  collections,
  translatableError,
}: {
  isNew: boolean;
  fields: EditableField[];
  roles: string[];
  values: TypeMetadataValues;
  onChange: (patch: Partial<TypeMetadataValues>) => void;
  errors: ValidationError[];
  /** The module's `public_route_prefix` setting — shown next to "Public"
   *  once it's switched on, since the prefix is DB-backed and the browser
   *  has no other way to know it (design §11). */
  publicRoutePrefix: string;
  /** Every content locale the module runs — named in "Translatable"'s help
   *  text, since that list is DB-backed configuration (design §4.4). */
  contentLocales: string[];
  /** Every collection the host declared (Phase 5 §6.1). Empty means this host
   *  declares none, and the control is not rendered at all — there is nothing
   *  to choose and a disabled select saying so would only puzzle. */
  collections: string[];
  /** A 409 from turning "Translatable" off while records in another locale
   *  exist (design §4.1) — not a field-scoped `422`, so it doesn't arrive
   *  through `errors` and is shown here instead. */
  translatableError?: string | null;
}) {
  const { t } = useT();
  const none = t('records.type_editor.pointer_none', { defaultValue: 'None' });
  // Only the field types the API accepts for each pointer
  // (`services/_schema.py::DISPLAY_FIELD_TYPES`/`SLUG_FIELD_TYPES`). Offering
  // a `json` display field or a `boolean` slug field meant a 422 on save at
  // best, and — before the server checked — every record titled `{'a': 1}`
  // or slugged `true`.
  const displayChoices = fields.filter((f) => displayFieldAllowed(f.type));
  const slugChoices = fields.filter((f) => slugFieldAllowed(f.type));

  // A pointer's target can stop being allowed out from under it — its type
  // changed (e.g. `text` to `longtext`) after it was picked (L7). Left
  // alone, the `<select>` drops the option and falls back to showing "None"
  // while `values.displayField`/`slugField` still hold the old key, so the
  // save that follows sends a pointer the control no longer shows and the
  // server refuses it (`DISPLAY_FIELD_TYPES`/`SLUG_FIELD_TYPES`,
  // `services/_schema.py`) with an error that contradicts the screen.
  // Clearing it here keeps the visible "None" and the actual form state in
  // agreement.
  useEffect(() => {
    if (values.displayField && !displayChoices.some((f) => f.key === values.displayField)) {
      onChange({ displayField: '' });
    }
    if (values.slugField && !slugChoices.some((f) => f.key === values.slugField)) {
      onChange({ slugField: '' });
    }
  }, [displayChoices, slugChoices, values.displayField, values.slugField, onChange]);

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

      <CollectionField
        isNew={isNew}
        value={values.collection}
        collections={collections}
        onChange={(collection) => onChange({ collection })}
        error={fieldMessage(errors, 'collection')}
      />

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

      <PublicField
        isPublic={values.isPublic}
        typeKey={values.key}
        publicRoutePrefix={publicRoutePrefix}
        onChange={(isPublic) => onChange({ isPublic })}
      />

      <div className="flex items-center gap-2 sm:col-span-2">
        <Switch
          id={ID.translatable}
          data-testid="records-translatable-toggle"
          checked={values.translatable}
          onCheckedChange={(checked) => onChange({ translatable: checked === true })}
        />
        <Label htmlFor={ID.translatable} className="font-normal">
          {t('records.type_editor.translatable', { defaultValue: 'Translatable' })}
        </Label>
      </div>
      <p className="-mt-2 text-sm text-muted-foreground sm:col-span-2">
        {t('records.type_editor.translatable_help', {
          locales: contentLocales.join(', '),
          defaultValue:
            'Records can exist in several languages ({locales}); each translation is its own record with its own slug.',
        })}
      </p>
      {translatableError && (
        <p
          className="-mt-2 text-sm text-destructive sm:col-span-2"
          role="alert"
          data-testid="records-translatable-error"
        >
          {translatableError}
        </p>
      )}

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
          onChange={(e) => onChange({ displayField: e.target.value })}
        >
          <NativeSelectOption value="">{none}</NativeSelectOption>
          {displayChoices.map((f) => (
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
          onChange={(e) => onChange({ slugField: e.target.value })}
        >
          <NativeSelectOption value="">{none}</NativeSelectOption>
          {slugChoices.map((f) => (
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
