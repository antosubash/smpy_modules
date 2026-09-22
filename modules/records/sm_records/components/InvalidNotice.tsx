import { useT } from '@simple-module-py/i18n';
import { humanizeDryRunMessage } from '../utils/dry-run-messages';
import { displayFieldKey } from '../utils/errors-display';
import type { ValidationError } from '../utils/types';

/**
 * "This record does not satisfy the current schema" — `record.invalid` as a
 * real notice, not a hidden record (design §8.3: "marked, not hidden"). The
 * per-field messages here are the same list `useRecordForm` folds into
 * `fieldErrors`, so the affected input's own error slot lights up too;
 * saving with fixes clears both at once, since the next response's `invalid`
 * is what `reset()` re-derives from.
 *
 * U9: `entry.message` is pydantic's own wording verbatim (§8.3 again — it is
 * carried straight from the dry run that marked the record), so it goes
 * through the same `humanizeDryRunMessage` the type editor's dry-run report
 * already applies — otherwise the same condition read "required, but this
 * record has no value for it" there and "Input should be a valid string"
 * here, for one and the same record.
 */
export function InvalidNotice({ errors }: { errors: ValidationError[] }) {
  const { t } = useT();
  if (errors.length === 0) return null;
  return (
    <div
      data-testid="records-invalid-notice"
      className="rounded-md border border-destructive/50 bg-destructive/5 p-3 text-sm"
      role="alert"
    >
      {/* A real `h2`, not a styled paragraph: the editor exposed exactly two
          headings before this pass, so a screen-reader user navigating by
          heading found nothing below the form (UX review R15). */}
      <h2 className="font-medium text-destructive">
        {t('records.editor.invalid.title', {
          defaultValue: 'This record does not satisfy the current schema',
        })}
      </h2>
      <ul className="mt-1 list-inside list-disc text-destructive">
        {errors.map((entry) => (
          <li key={`${entry.field}:${entry.message}`}>
            {displayFieldKey(entry.field)}: {humanizeDryRunMessage(t, entry.message)}
          </li>
        ))}
      </ul>
    </div>
  );
}
