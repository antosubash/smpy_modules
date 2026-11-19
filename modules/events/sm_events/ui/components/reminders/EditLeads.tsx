/** A row's lead times, edited in place: the same closed set the control offers. */
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useEffect, useId, useRef, useState } from 'react';
import { leadLabel } from '../../reminders/leadText';
import { errorText } from '../../utils/api';
import { type Lead, reminderStatusOnce, setFollow } from '../../utils/api-reminders';
import { keys, useT } from '../../utils/i18n';

export function EditLeads({
  eventId,
  leads,
  onSaved,
  onClose,
}: {
  eventId: string;
  leads: Lead[];
  onSaved: () => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.reminders.control;
  const base = useId();
  const [offered, setOffered] = useState<Lead[]>([]);
  const [picked, setPicked] = useState<Lead[]>(leads);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    void reminderStatusOnce().then((s) => setOffered(s.leads));
  }, []);
  useEffect(() => {
    if (offered.length > 0) first.current?.focus();
  }, [offered]);
  return (
    // biome-ignore lint/a11y/useSemanticElements: a fieldset would restyle the table cell
    <div
      role="group"
      aria-label={t(copy.panel_title)}
      className="space-y-2"
      onKeyDown={(event) => {
        if (event.key === 'Escape') onClose();
      }}
    >
      <ul className="space-y-1">
        {offered.map((lead, index) => (
          <li key={lead} className="flex items-center gap-2">
            <Checkbox
              ref={index === 0 ? first : undefined}
              id={`${base}-${lead}`}
              checked={picked.includes(lead)}
              onCheckedChange={(on) =>
                setPicked((now) => (on ? [...now, lead] : now.filter((x) => x !== lead)))
              }
            />
            <Label htmlFor={`${base}-${lead}`}>{leadLabel(t, lead)}</Label>
          </li>
        ))}
      </ul>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          disabled={saving || picked.length === 0}
          onClick={async () => {
            setSaving(true);
            try {
              await setFollow(
                eventId,
                [...picked].sort((a, b) => a - b),
              );
              onSaved();
            } catch (e) {
              setError(errorText(e));
              setSaving(false);
            }
          }}
        >
          {saving ? t(copy.saving) : t(copy.save)}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onClose}>
          {t(keys.events.common.cancel)}
        </Button>
      </div>
    </div>
  );
}
