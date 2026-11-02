import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';

import { keys, useT } from '../../utils/i18n';
import type { ImportMapping } from '../../utils/types';

export type MappingProp = Exclude<keyof ImportMapping, 'filename_pattern'>;

const FIELD = {
  url_prop: keys.images.imports.wizard.field.url_prop,
  image_prop: keys.images.imports.wizard.field.image_prop,
  lat_prop: keys.images.imports.wizard.field.lat_prop,
  lng_prop: keys.images.imports.wizard.field.lng_prop,
  datetime_prop: keys.images.imports.wizard.field.datetime_prop,
  external_id_prop: keys.images.imports.wizard.field.external_id_prop,
  group_key_prop: keys.images.imports.wizard.field.group_key_prop,
  group_role_prop: keys.images.imports.wizard.field.group_role_prop,
} satisfies Record<MappingProp, string>;

/**
 * The property each image field is read from: a text input that suggests the
 * properties the preview found. It stays a free input because a URL import
 * fetched by the server has no local preview to choose from, and because a
 * dotted path (`meta.photo.url`) is a valid property.
 */
export function MappingFields({
  fields,
  properties,
  mapping,
  suggested,
  onChange,
}: {
  fields: MappingProp[];
  properties: string[];
  mapping: ImportMapping;
  /** The fields the preview filled in; marked until the person changes them. */
  suggested: ReadonlySet<string>;
  onChange: (field: MappingProp, value: string | undefined) => void;
}) {
  const { t } = useT();
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <datalist id="images-map-properties">
        {properties.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      {fields.map((field) => (
        <div key={field} className="grid gap-1">
          <Label htmlFor={`images-map-${field}`}>
            {t(FIELD[field])}
            {suggested.has(field) && (
              <span className="ml-2 text-xs text-muted-foreground">
                {t(keys.images.imports.wizard.detected)}
              </span>
            )}
          </Label>
          <Input
            id={`images-map-${field}`}
            data-testid={`images-map-${field}`}
            list="images-map-properties"
            maxLength={200}
            value={mapping[field] ?? ''}
            onChange={(e) => onChange(field, e.target.value || undefined)}
          />
        </div>
      ))}
    </div>
  );
}

/** The ZIP's one mapping, and the optional grouping pattern of a GeoJSON import. */
export function FilenamePattern({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const { t } = useT();
  return (
    <div className="grid gap-1">
      <Label htmlFor="images-map-filename-pattern">
        {t(keys.images.imports.wizard.filename_pattern)}
      </Label>
      <Input
        id="images-map-filename-pattern"
        data-testid="images-map-filename-pattern"
        value={value}
        maxLength={500}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="text-xs text-muted-foreground">
        {t(keys.images.imports.wizard.filename_pattern_hint)}
      </p>
    </div>
  );
}
