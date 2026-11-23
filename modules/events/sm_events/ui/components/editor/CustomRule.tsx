import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { keys, useT } from '../../utils/i18n';
import { RRULE_MAX_LEN } from '../../utils/recurrence';

/** A rule the form cannot express. It is shown as it is stored and sent back
 *  unchanged: the text becomes editable only after "Edit as text", and picking
 *  a repeat above replaces it. */
export function CustomRule({
  value,
  editing,
  onEdit,
  onChange,
}: {
  value: string;
  editing: boolean;
  onEdit: () => void;
  onChange: (rule: string) => void;
}) {
  const { t } = useT();
  const copy = keys.events.recurrence;
  return (
    <div className="grid gap-2">
      <Label htmlFor="event-rrule-text">{t(copy.custom)}</Label>
      <Input
        id="event-rrule-text"
        className="font-mono"
        maxLength={RRULE_MAX_LEN}
        readOnly={!editing}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="text-sm text-muted-foreground dark:text-zinc-400">
        {t(editing ? copy.custom_hint : copy.custom_readonly)}
      </p>
      {!editing && (
        <div>
          <Button type="button" variant="outline" size="sm" onClick={onEdit}>
            {t(copy.custom_edit)}
          </Button>
        </div>
      )}
    </div>
  );
}
