import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';

import type { LabelMap } from '../hooks/useRelationLabels';
import type { RelationValue } from '../utils/values';

/** A glyph, not copy — the accessible name is the translated `aria-label`. */
const REMOVE_GLYPH = '×';

/**
 * What a relation field already points at, as removable chips.
 *
 * Split out of `RelationPicker` when that file took on the WAI-ARIA combobox
 * keyboard handling (UX review R20) and ran past the 300-line cap; the seam
 * is the one that was already there, between "what is chosen" and "how you
 * choose".
 *
 * Each remove button is named after the chip it removes (R11): five chips on
 * one field otherwise give a screen reader five buttons called "Remove", and
 * it can tell the user about none of them.
 */
export function RelationChips({
  selected,
  labels,
  disabled,
  onRemove,
}: {
  selected: RelationValue[];
  labels: LabelMap;
  disabled?: boolean;
  onRemove: (uuid: string) => void;
}) {
  const { t } = useT();
  if (selected.length === 0) return null;
  const missingLabel = t('records.relation.missing', { defaultValue: 'Missing record' });
  const restrictedLabel = t('records.relation.restricted', { defaultValue: 'Restricted' });
  return (
    <div className="flex flex-wrap gap-2">
      {selected.map((ref) => {
        const entry = labels[ref.uuid];
        const restricted = entry?.restricted ?? false;
        const gone = entry !== undefined && !restricted && entry.title === null;
        const chipText = restricted
          ? restrictedLabel
          : gone
            ? missingLabel
            : (entry?.title ?? ref.uuid);
        return (
          <Badge
            key={ref.uuid}
            variant={gone ? 'destructive' : restricted ? 'outline' : 'secondary'}
            className={`gap-1 py-1 ${restricted ? 'text-muted-foreground' : ''}`}
            data-testid={restricted ? 'records-relation-chip-restricted' : undefined}
          >
            <span>{chipText}</span>
            <button
              type="button"
              disabled={disabled}
              aria-label={t('records.relation.remove_named', {
                title: chipText,
                defaultValue: 'Remove {title}',
              })}
              className="ml-1 opacity-70 hover:opacity-100 disabled:opacity-40"
              onClick={() => onRemove(ref.uuid)}
            >
              {REMOVE_GLYPH}
            </button>
          </Badge>
        );
      })}
    </div>
  );
}
