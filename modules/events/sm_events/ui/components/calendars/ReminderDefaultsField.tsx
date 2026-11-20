/** Which lead times "Remind me" suggests on a calendar, or the site's own suggestion. */
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useId } from 'react';
import { leadLabel } from '../../reminders/leadText';
import { keys, useT } from '../../utils/i18n';

/** The closed set the server accepts; it checks every value again. */
const LEADS = [15, 60, 1440, 10080];

export function ReminderDefaultsField({
  value,
  onChange,
}: {
  /** `null`: the site's suggestion. */
  value: number[] | null;
  onChange: (next: number[] | null) => void;
}) {
  const { t } = useT();
  const copy = keys.events.reminders.defaults;
  const base = useId();
  return (
    // biome-ignore lint/a11y/useSemanticElements: a fieldset would restyle the dialog's grid
    <div role="group" aria-labelledby={`${base}-label`} className="grid gap-2">
      <span id={`${base}-label`} className="text-sm font-medium">
        {t(copy.label)}
      </span>
      <div className="flex items-center gap-2">
        <Checkbox
          id={`${base}-site`}
          checked={value === null}
          onCheckedChange={(on) => onChange(on ? null : [])}
        />
        <Label htmlFor={`${base}-site`}>{t(copy.site_default)}</Label>
      </div>
      {value !== null ? (
        <ul className="grid gap-1 pl-6">
          {LEADS.map((lead) => (
            <li key={lead} className="flex items-center gap-2">
              <Checkbox
                id={`${base}-${lead}`}
                checked={value.includes(lead)}
                onCheckedChange={(on) =>
                  onChange(
                    on ? [...value, lead].sort((a, b) => a - b) : value.filter((x) => x !== lead),
                  )
                }
              />
              <Label htmlFor={`${base}-${lead}`}>{leadLabel(t, lead)}</Label>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-xs text-muted-foreground dark:text-zinc-400">{t(copy.help)}</p>
    </div>
  );
}
