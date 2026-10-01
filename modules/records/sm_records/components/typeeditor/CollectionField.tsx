import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

const ID = 'type-editor-collection';

/**
 * Which table set a type's documents live in — Phase 5 §6.2.
 *
 * It renders in three states, and which one is not a styling choice:
 *
 * - **New type, host declares collections** — a select, because this is the
 *   only request that may set it.
 * - **Existing type in a collection** — read-only text. A `PATCH` that changes
 *   it is a 409, so an editable control would offer an action that cannot
 *   succeed.
 * - **Anything else** — nothing at all. On a host that declares no collection
 *   there is nothing to choose, and a disabled select saying "Shared tables"
 *   would be a control for a feature that host does not have. That is the
 *   inert property of §6.5, as the UI sees it.
 *
 * Split out of `TypeMetadataForm` for the 300-line cap.
 */
export function CollectionField({
  isNew,
  value,
  collections,
  onChange,
  error,
}: {
  isNew: boolean;
  /** `''` is the shared tables. */
  value: string;
  /** `props.collections` — what `declare_collection()` this host has run. */
  collections: string[];
  onChange: (collection: string) => void;
  error?: string;
}) {
  const { t } = useT();
  if (isNew ? collections.length === 0 : !value) return null;

  return (
    <div className="grid gap-1.5" data-testid="records-collection">
      <Label htmlFor={ID}>
        {t('records.type_editor.collection', { defaultValue: 'Collection' })}
      </Label>
      {isNew ? (
        <NativeSelect id={ID} value={value} onChange={(e) => onChange(e.target.value)}>
          <NativeSelectOption value="">
            {t('records.type_editor.collection_shared', { defaultValue: 'Shared tables' })}
          </NativeSelectOption>
          {collections.map((name) => (
            <NativeSelectOption key={name} value={name}>
              {name}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      ) : (
        <Input id={ID} value={value} disabled readOnly />
      )}
      <p className="text-sm text-muted-foreground">
        {isNew
          ? t('records.type_editor.collection_help', {
              defaultValue:
                "Gives this type its own document and index tables. Chosen once — a type can't be moved between collections later.",
            })
          : t('records.type_editor.collection_immutable', {
              defaultValue: "A type can't be moved between collections once it is created.",
            })}
      </p>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
