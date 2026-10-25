import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { keys, useT } from '../../utils/i18n';
import { editableFields, SUBMITTABLE_TYPES } from '../../utils/public-submissions';
import type { EditableField } from './types';

/**
 * Which ordinary fields a visitor fills in (`public_submissions.public_fields`,
 * #101). One row per field, in the field list's order, which is the order the
 * form renders them in. A field type no website form can take is shown greyed
 * with the reason rather than hidden, and a required field with no default
 * that is left unticked says why the form can't be turned on.
 */
export function PublicFieldsChecklist({
  fields,
  selected,
  missing,
  onChange,
}: {
  fields: EditableField[];
  selected: string[];
  /** Required fields with no default that are not ticked. */
  missing: string[];
  onChange: (next: string[]) => void;
}) {
  const { t } = useT();
  const candidates = editableFields(fields).filter((field) => field.key);
  const toggle = (key: string, on: boolean) => {
    // Kept in field-list order whatever order the boxes were ticked in.
    const next = new Set(selected);
    if (on) next.add(key);
    else next.delete(key);
    onChange(candidates.map((field) => field.key).filter((k) => next.has(k)));
  };

  return (
    <fieldset className="grid gap-2" data-testid="records-public-fields">
      <legend className="text-sm font-medium">
        {t(keys.records.public_submissions.public_fields)}
      </legend>
      <p className="text-sm text-muted-foreground">
        {t(keys.records.public_submissions.public_fields_help)}
      </p>
      {candidates.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {t(keys.records.public_submissions.public_fields_none)}
        </p>
      )}
      {candidates.map((field) => {
        const id = `public-field-${field.uid}`;
        // `config.settle`: a unique field cannot be public (a duplicate's 409
        // would tell a visitor what another visitor sent).
        const eligible = SUBMITTABLE_TYPES.has(field.type) && !field.unique;
        const ticked = selected.includes(field.key);
        return (
          <div key={field.uid} className="grid gap-0.5">
            <div className="flex items-center gap-2">
              <Checkbox
                id={id}
                checked={ticked}
                // A ticked field whose type changed to one a visitor cannot
                // fill in stays untickable, or the server's refusal of it
                // (`config.settle`) could never be cleared from this screen.
                disabled={!eligible && !ticked}
                onCheckedChange={(checked) => toggle(field.key, checked === true)}
              />
              <Label htmlFor={id} className="font-normal">
                {field.label || field.key}{' '}
                <span className="font-mono text-xs text-muted-foreground">({field.key})</span>
              </Label>
            </div>
            {!eligible && (
              <p className="ml-6 text-xs text-muted-foreground">
                {field.unique
                  ? t(keys.records.public_submissions.public_field_unique)
                  : t(keys.records.public_submissions.public_field_ineligible, {
                      type: field.type,
                    })}
              </p>
            )}
            {missing.includes(field.key) && (
              <p className="ml-6 text-xs text-destructive">
                {t(keys.records.public_submissions.public_field_required)}
              </p>
            )}
          </div>
        );
      })}
    </fieldset>
  );
}
