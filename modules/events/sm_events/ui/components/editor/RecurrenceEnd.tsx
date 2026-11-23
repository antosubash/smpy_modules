import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { fieldErrorId, invalidProps, requiredText } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import { COUNT_MAX, type RuleEnd, type RuleForm } from '../../utils/recurrence';

/** How the series ends: never, after N times or on a date. An "on a date" end
 *  with the date cleared stays on screen with a required-field error; the rule
 *  carries no `UNTIL` meanwhile and the editor reports the form as incomplete. */
export function RecurrenceEnd({
  form,
  start,
  kind,
  untilMissing,
  onEnd,
}: {
  form: RuleForm;
  start: string;
  kind: string;
  untilMissing: boolean;
  /** `dateless`: the end is "on a date" and has none yet. */
  onEnd: (end: RuleEnd, dateless: boolean) => void;
}) {
  const { t } = useT();
  const copy = keys.events.recurrence;
  const message = untilMissing ? requiredText() : undefined;
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="grid gap-2">
        <Label htmlFor="event-rrule-end">{t(copy.ends)}</Label>
        <NativeSelect
          id="event-rrule-end"
          value={kind}
          onChange={(e) => {
            const next = e.target.value;
            if (next === 'count') onEnd({ kind: 'count', count: 10 }, false);
            else if (next === 'until') onEnd({ kind: 'until', date: start.slice(0, 10) }, false);
            else onEnd({ kind: 'never' }, false);
          }}
        >
          <option value="never">{t(copy.end_never)}</option>
          <option value="count">{t(copy.end_count)}</option>
          <option value="until">{t(copy.end_date)}</option>
        </NativeSelect>
      </div>
      {form.end.kind === 'count' && (
        <div className="grid gap-2">
          <Label htmlFor="event-rrule-count">{t(copy.count)}</Label>
          <Input
            id="event-rrule-count"
            type="number"
            min={1}
            max={COUNT_MAX}
            className="w-24"
            value={form.end.count}
            onChange={(e) => onEnd({ kind: 'count', count: Number(e.target.value) || 1 }, false)}
          />
        </div>
      )}
      {kind === 'until' && (
        <div className="grid gap-2">
          <Label htmlFor="event-rrule-until">{t(copy.until)}</Label>
          <Input
            id="event-rrule-until"
            type="date"
            value={form.end.kind === 'until' ? form.end.date : ''}
            {...invalidProps('event-rrule-until', message)}
            onChange={(e) => onEnd({ kind: 'until', date: e.target.value }, e.target.value === '')}
          />
          <FieldError id={fieldErrorId('event-rrule-until')}>{message}</FieldError>
        </div>
      )}
    </div>
  );
}
