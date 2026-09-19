import { useT } from '@simple-module-py/i18n';

import type { ValidationError } from '../utils/types';

/**
 * "This record does not satisfy the current schema" — `record.invalid` as a
 * real notice, not a hidden record (design §8.3: "marked, not hidden"). The
 * per-field messages here are the same list `useRecordForm` folds into
 * `fieldErrors`, so the affected input's own error slot lights up too;
 * saving with fixes clears both at once, since the next response's `invalid`
 * is what `reset()` re-derives from.
 */
export function InvalidNotice({ errors }: { errors: ValidationError[] }) {
  const { t } = useT();
  if (errors.length === 0) return null;
  return (
    <div
      className="rounded-md border border-destructive/50 bg-destructive/5 p-3 text-sm"
      role="alert"
    >
      <p className="font-medium text-destructive">
        {t('records.editor.invalid.title', {
          defaultValue: 'This record does not satisfy the current schema',
        })}
      </p>
      <ul className="mt-1 list-inside list-disc text-destructive">
        {errors.map((entry) => (
          <li key={`${entry.field}:${entry.message}`}>
            {entry.field}: {entry.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
