import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

import { localeLabel } from '../utils/locale';
import type { RecordStatus, ValidationError } from '../utils/types';

const SLUG_ID = 'record-slug';
const POSITION_ID = 'record-position';
const STATUS_ID = 'record-status';
const LOCALE_ID = 'record-locale';

/** The envelope keys whose messages belong to the "Advanced" disclosure —
 *  it opens itself when one of them arrives, so a 422 about a slug is never
 *  hidden behind a closed `<details>` (UX review R6/R16). */
const ADVANCED_KEYS = ['slug', 'position'];

function fieldMessage(errors: ValidationError[], field: string): string | undefined {
  return errors.find((e) => e.field === field)?.message;
}

export function hasAdvancedError(errors: ValidationError[]): boolean {
  return errors.some((e) => ADVANCED_KEYS.includes(e.field));
}

/**
 * Status and Language: the two record-level choices that belong *with* the
 * save, in the page header next to it.
 *
 * Before R16 these opened the form, above the record's own fields — the
 * plumbing outranking the payload, with Slug and Position (see
 * `RecordAdvancedFields`) in between the person and the thing they came to
 * type. Status stays visible because it is the one envelope value an editor
 * changes on nearly every save.
 */
export function RecordHeaderFields({
  status,
  envelope,
  onStatusChange,
  locale,
  locales,
  onLocaleChange,
}: {
  status: RecordStatus;
  envelope: ValidationError[];
  onStatusChange: (next: RecordStatus) => void;
  /** Only meaningful together with `locales`/`onLocaleChange`, and only ever
   *  passed by the caller for a *new* record on a translatable type with more
   *  than one content locale — a record's language is fixed for its lifetime
   *  (design §4.3), so this input never appears once the record exists. */
  locale?: string;
  locales?: string[];
  onLocaleChange?: (next: string) => void;
}) {
  const { t } = useT();
  const showLocale = (locales?.length ?? 0) > 1 && onLocaleChange !== undefined;
  const statusError = fieldMessage(envelope, 'status');
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {showLocale && (
        <div className="flex items-center gap-2">
          <Label htmlFor={LOCALE_ID} className="text-sm text-muted-foreground">
            {t('records.editor.locale_label', { defaultValue: 'Language' })}
          </Label>
          <NativeSelect
            id={LOCALE_ID}
            data-testid="records-locale-select"
            value={locale}
            onChange={(e) => onLocaleChange?.(e.target.value)}
          >
            {(locales ?? []).map((tag) => (
              <NativeSelectOption key={tag} value={tag}>
                {localeLabel(tag)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
      )}
      <div className="flex items-center gap-2">
        <Label htmlFor={STATUS_ID} className="text-sm text-muted-foreground">
          {t('records.records.status', { defaultValue: 'Status' })}
        </Label>
        <NativeSelect
          id={STATUS_ID}
          value={status}
          aria-invalid={!!statusError}
          onChange={(e) => onStatusChange(e.target.value as RecordStatus)}
        >
          <NativeSelectOption value="draft">
            {t('records.records.draft', { defaultValue: 'Draft' })}
          </NativeSelectOption>
          <NativeSelectOption value="published">
            {t('records.records.published', { defaultValue: 'Published' })}
          </NativeSelectOption>
        </NativeSelect>
      </div>
      {statusError && (
        <p className="w-full text-sm text-destructive" role="alert">
          {statusError}
        </p>
      )}
    </div>
  );
}

/**
 * Slug and Position, behind a disclosure under the form (R16).
 *
 * Both are derivable or defaulted — the type derives a slug from its
 * `slug_field`, and position is 0 on everything until someone orders a public
 * list by hand — so an empty Slug box as the *second* control on a new-record
 * screen mostly invited typing a slug that then competed with the derived
 * one. Each now carries the line of help that says what leaving it alone
 * does.
 *
 * `<details>` rather than a state-driven panel: it is a disclosure, the
 * browser's own is keyboard- and screen-reader-correct for free, and `open`
 * is forced when a message inside needs to be seen.
 */
export function RecordAdvancedFields({
  slug,
  position,
  envelope,
  onSlugChange,
  onPositionChange,
  slugSourceLabel,
}: {
  slug: string;
  position: string;
  envelope: ValidationError[];
  onSlugChange: (next: string) => void;
  onPositionChange: (next: string) => void;
  /** The label of the type's `slug_field`, when it has one — the help line
   *  names the field the slug comes from rather than saying "a field". */
  slugSourceLabel?: string;
}) {
  const { t } = useT();
  const slugError = fieldMessage(envelope, 'slug');
  const positionError = fieldMessage(envelope, 'position');
  return (
    <details open={hasAdvancedError(envelope)} data-testid="records-advanced-fields">
      <summary className="cursor-pointer text-sm font-medium text-muted-foreground">
        {t('records.editor.advanced', { defaultValue: 'Advanced' })}
      </summary>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor={SLUG_ID}>
            {t('records.editor.slug_label', { defaultValue: 'Slug' })}
          </Label>
          <Input
            id={SLUG_ID}
            value={slug}
            aria-invalid={!!slugError}
            onChange={(e) => onSlugChange(e.target.value)}
          />
          <p className="text-sm text-muted-foreground">
            {slugSourceLabel
              ? t('records.editor.slug_help_derived', {
                  field: slugSourceLabel,
                  defaultValue: 'Leave blank to derive it from {field}.',
                })
              : t('records.editor.slug_help', {
                  defaultValue: 'The address this record gets in a public URL.',
                })}
          </p>
          {slugError && <p className="text-sm text-destructive">{slugError}</p>}
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={POSITION_ID}>
            {t('records.editor.position_label', { defaultValue: 'Position' })}
          </Label>
          <Input
            id={POSITION_ID}
            type="number"
            value={position}
            aria-invalid={!!positionError}
            onChange={(e) => onPositionChange(e.target.value)}
          />
          <p className="text-sm text-muted-foreground">
            {t('records.editor.position_help', {
              defaultValue: 'Orders this record in a public list. Leave it at 0 to sort by date.',
            })}
          </p>
          {positionError && <p className="text-sm text-destructive">{positionError}</p>}
        </div>
      </div>
    </details>
  );
}
