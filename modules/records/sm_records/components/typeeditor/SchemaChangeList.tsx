import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';

import type { ChangeClass, SchemaPreview } from '../../utils/types';
import { changeKindLabel, changeWhatLabel } from './changeLabels';

const KIND_BADGE_CLASS: Record<ChangeClass, string> = {
  additive: 'border-emerald-500 text-emerald-600',
  index_affecting: 'border-blue-500 text-blue-600',
  restrictive: 'border-amber-500 text-amber-600',
  destructive: '',
};

/** The overall classification of a `SchemaPreview` as a small colour-coded
 *  badge — destructive uses the shadcn `destructive` variant outright (it is
 *  the one class the module wants to actually alarm on); the other three are
 *  outline badges tinted the way `FieldList`'s existing amber notice already
 *  is, so the vocabulary of "this colour means this severity" stays the same
 *  screen to screen. */
function ChangeKindBadge({ kind }: { kind: ChangeClass }) {
  const { t } = useT();
  return (
    <Badge
      variant={kind === 'destructive' ? 'destructive' : 'outline'}
      className={KIND_BADGE_CLASS[kind]}
    >
      {changeKindLabel(t, kind)}
    </Badge>
  );
}

/** The badge plus the change list from a `SchemaPreview` — one line per
 *  `SchemaChange`: the field key and its `what`, translated via the
 *  `type_editor.change.<what>` family (design contract). */
export function SchemaChangeList({ preview }: { preview: SchemaPreview }) {
  const { t } = useT();
  return (
    <div className="space-y-3">
      <ChangeKindBadge kind={preview.kind} />
      {preview.changes.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t('records.type_editor.preview.no_changes', { defaultValue: 'No changes.' })}
        </p>
      ) : (
        <ul className="space-y-1 text-sm">
          {preview.changes.map((change) => (
            <li
              key={`${change.field_key}:${change.what}:${JSON.stringify(change.before)}:${JSON.stringify(change.after)}`}
            >
              <span className="font-mono">
                {change.field_key === '*'
                  ? t('records.type_editor.reindex.whole_type', { defaultValue: 'Whole type' })
                  : change.field_key}
              </span>
              {' — '}
              {changeWhatLabel(t, change.what)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
