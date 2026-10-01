import { useT } from '@simple-module-py/i18n';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';

/**
 * One row's tick box, and the header's "everything on this page" one.
 *
 * Shared by the table and the card list so the phone layout cannot drift from
 * the desktop one — the same reason `RecordRowAction` is one component.
 *
 * **Shift+click is read off the click**, not off a key listener and not off
 * `onCheckedChange`: that one says *that* the box changed and never *how the
 * operator asked for it*, and the range gesture is entirely about the how.
 *
 * `onClick` and nothing else answers the keyboard too, which is why there is
 * no key handling here to get wrong: Radix's `Checkbox` renders a real
 * button, so Space on the focused row emits a click with `shiftKey` false —
 * one row, which is what Space means.
 */
export function RecordSelectCell({
  checked,
  title,
  onToggle,
}: {
  checked: boolean;
  /** The record's display title, for the accessible name — twenty-five boxes
   *  all called "Select" is a list a screen-reader user cannot navigate. */
  title: string;
  onToggle: (extend: boolean) => void;
}) {
  const { t } = useT();
  return (
    <Checkbox
      checked={checked}
      data-testid="records-select-row"
      aria-label={t('records.bulk.select_record', {
        title,
        defaultValue: 'Select {title}',
      })}
      onClick={(event) => onToggle(event.shiftKey)}
    />
  );
}

/** The header box: ticks or clears every row on this page (and only this
 *  page — a selection the operator cannot see is not one they chose). */
export function RecordSelectAllCell({
  checked,
  indeterminate,
  onToggle,
}: {
  checked: boolean;
  indeterminate: boolean;
  onToggle: () => void;
}) {
  const { t } = useT();
  return (
    <Checkbox
      checked={indeterminate ? 'indeterminate' : checked}
      data-testid="records-select-all"
      aria-label={t('records.bulk.select_all', {
        defaultValue: 'Select every record on this page',
      })}
      onCheckedChange={() => onToggle()}
    />
  );
}
