import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Switch } from '@simple-module-py/ui/components/ui/switch';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useRef } from 'react';
import { keys, type Translate, useT } from '../../utils/i18n';
import type { TenancyMode, ValidationError } from '../../utils/types';
import { CollectionField } from './CollectionField';
import { fieldMessage } from './errors';
import { keyFromLabel, pluralFromLabel } from './formHelpers';
import { IconField } from './IconField';
import { PublicField } from './PublicField';
import { RolesMultiSelect } from './RolesMultiSelect';
import { type KeyError as KeyErrorCode, keyValid, MAX_KEY_LEN, MAX_LABEL_LEN } from './rules';
import { SidebarField } from './SidebarField';
import type { TypeMetadataValues } from './types';

const ID = {
  key: 'type-editor-key',
  label: 'type-editor-label',
  labelPlural: 'type-editor-label-plural',
  description: 'type-editor-description',
  translatable: 'type-editor-translatable',
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
  roles,
  values,
  onChange,
  errors,
  publicRoutePrefix,
  contentLocales,
  collections,
  translatableError,
  tenancyMode,
}: {
  isNew: boolean;
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
  /** From the page's `tenancy_mode` view prop — `SidebarField` hides "Show in
   *  sidebar" for a note instead once this is `'multi'` (design §I). */
  tenancyMode?: TenancyMode;
}) {
  const { t } = useT();
  // Which of the two derived fields the operator has taken over. Refs, not
  // state: nothing renders off them, and a re-render caused by the label
  // they are derived from must not reset them (R19).
  const keyTouched = useRef(!isNew);
  const pluralTouched = useRef(!isNew);
  // The type key answers to exactly the rule a *field* key does
  // (`constants.TYPE_KEY_PATTERN`), which `rules.ts` already mirrors — so
  // "Blog Posts" is refused here, in place, instead of coming back as a 422
  // from Save on the one value that can never be corrected afterwards.
  const localKeyError = isNew && values.key ? keyValid(values.key, []) : null;

  /** Typing a Label fills in the Key and the Plural label until either is
   *  edited directly — the new-type form's only two answers that can be
   *  guessed, and the Key is the one that is permanent. */
  const onLabelChange = (label: string) => {
    const patch: Partial<TypeMetadataValues> = { label };
    if (isNew && !keyTouched.current) patch.key = keyFromLabel(label);
    if (!pluralTouched.current) patch.labelPlural = pluralFromLabel(label);
    onChange(patch);
  };

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="grid gap-1.5">
        <Label htmlFor={ID.key}>{t(keys.records.types.key)}</Label>
        {isNew ? (
          <>
            <Input
              id={ID.key}
              value={values.key}
              maxLength={MAX_KEY_LEN}
              placeholder={t(keys.records.type_editor.key_placeholder)}
              onChange={(e) => {
                keyTouched.current = true;
                onChange({ key: e.target.value });
              }}
              aria-invalid={!!localKeyError || !!fieldMessage(errors, 'key')}
            />
            <p className="text-sm text-muted-foreground">
              {t(keys.records.type_editor.key_new_help)}
            </p>
            {localKeyError && (
              <p className="text-sm text-destructive" data-testid="records-type-key-error">
                {typeKeyError(t, localKeyError, values.key)}
              </p>
            )}
          </>
        ) : (
          <>
            <Input id={ID.key} value={values.key} disabled readOnly />
            <p className="text-sm text-muted-foreground">
              {t(keys.records.type_editor.key_immutable)}
            </p>
          </>
        )}
        <FieldError message={fieldMessage(errors, 'key')} />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={ID.label}>{t(keys.records.types.label)}</Label>
        <Input
          id={ID.label}
          value={values.label}
          maxLength={MAX_LABEL_LEN}
          onChange={(e) => onLabelChange(e.target.value)}
          aria-invalid={!!fieldMessage(errors, 'label')}
        />
        <FieldError message={fieldMessage(errors, 'label')} />
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={ID.labelPlural}>{t(keys.records.types.label_plural)}</Label>
        <Input
          id={ID.labelPlural}
          value={values.labelPlural}
          maxLength={MAX_LABEL_LEN}
          onChange={(e) => {
            pluralTouched.current = true;
            onChange({ labelPlural: e.target.value });
          }}
          aria-invalid={!!fieldMessage(errors, 'label_plural')}
        />
        <FieldError message={fieldMessage(errors, 'label_plural')} />
      </div>

      <IconField
        value={values.icon}
        error={fieldMessage(errors, 'icon')}
        onChange={(icon) => onChange({ icon })}
      />

      <CollectionField
        isNew={isNew}
        value={values.collection}
        collections={collections}
        onChange={(collection) => onChange({ collection })}
        error={fieldMessage(errors, 'collection')}
      />

      <div className="grid gap-1.5 sm:col-span-2">
        <Label htmlFor={ID.description}>{t(keys.records.types.description)}</Label>
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
          {t(keys.records.type_editor.translatable)}
        </Label>
      </div>
      <p className="-mt-2 text-sm text-muted-foreground sm:col-span-2">
        {t(keys.records.type_editor.translatable_help, {
          locales: contentLocales.join(', '),
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

      <SidebarField
        showInMenu={values.showInMenu}
        labelPlural={values.labelPlural}
        tenancyMode={tenancyMode}
        onChange={(showInMenu) => onChange({ showInMenu })}
      />

      <div className="grid gap-1.5 sm:col-span-2">
        <Label>{t(keys.records.type_editor.allowed_roles)}</Label>
        <RolesMultiSelect
          idPrefix="type-editor-role"
          roles={roles}
          selected={values.allowedRoles}
          onChange={(next) => onChange({ allowedRoles: next })}
        />
        <p className="text-sm text-muted-foreground">
          {t(keys.records.type_editor.allowed_roles_help)}
        </p>
        <FieldError message={fieldMessage(errors, 'allowed_roles')} />
      </div>
    </div>
  );
}

/** The type key's inline refusals — the same set `rules.ts::keyValid`
 *  returns for a field key, worded for a type (R19). */
function typeKeyError(t: Translate, code: KeyErrorCode, key: string): string {
  return t(keys.records.type_editor.type_key_error[code], { key, max: MAX_KEY_LEN });
}
