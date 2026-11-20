import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { type FormEvent, useState } from 'react';
import {
  createSubscription,
  type Subscription,
  type SubscriptionPatch,
  subscriptionErrorText,
  updateSubscription,
} from '../../utils/api-subscriptions';
import { keys, useT } from '../../utils/i18n';

type Props = {
  calendarId: string;
  /** The subscription being edited; `null` adds one. */
  editing: Subscription | null;
  isPublicCalendar: boolean;
  canPublish: boolean;
  defaultMinutes: number;
  onDone: () => void;
  onCancel: () => void;
};

/** Add or edit. The address field starts empty on an edit and is sent only when typed; it is
 *  cleared as soon as the form closes, so it is never kept on screen. */
export function SubscriptionForm({
  calendarId,
  editing,
  isPublicCalendar,
  canPublish,
  defaultMinutes,
  onDone,
  onCancel,
}: Props) {
  const { t } = useT();
  const copy = keys.events.subscriptions;
  const [url, setUrl] = useState('');
  const [label, setLabel] = useState(editing?.label ?? '');
  const [color, setColor] = useState(editing?.color ?? '');
  const [minutes, setMinutes] = useState(editing?.refresh_minutes?.toString() ?? '');
  const [shown, setShown] = useState(editing?.public ?? false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const canShow = canPublish && isPublicCalendar;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    const wanted = {
      label: label.trim(),
      color: color.trim() === '' ? null : color.trim(),
      refresh_minutes: minutes.trim() === '' ? null : Number(minutes),
      public: shown,
    };
    try {
      if (editing) {
        const patch: SubscriptionPatch = { expected: editing.version };
        if (url.trim() !== '') patch.url = url.trim();
        if (wanted.label !== editing.label) patch.label = wanted.label;
        if (wanted.color !== editing.color) patch.color = wanted.color;
        if (wanted.refresh_minutes !== editing.refresh_minutes)
          patch.refresh_minutes = wanted.refresh_minutes;
        if (wanted.public !== editing.public) patch.public = wanted.public;
        await updateSubscription(editing.id, patch);
      } else {
        await createSubscription(calendarId, { url: url.trim(), ...wanted });
      }
      setUrl('');
      onDone();
    } catch (e) {
      setError(subscriptionErrorText(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="space-y-3 rounded border p-3"
      data-testid="subscription-form"
      aria-label={t(editing ? copy.edit_title : copy.add_title)}
    >
      <div className="space-y-1">
        <Label htmlFor="events-sub-url">{t(copy.form.url)}</Label>
        <Input
          id="events-sub-url"
          type="url"
          autoComplete="off"
          spellCheck={false}
          required={!editing}
          value={url}
          placeholder={editing ? t(copy.form.url_keep) : 'https://'}
          onChange={(e) => setUrl(e.target.value)}
          aria-describedby="events-sub-url-hint"
        />
        <p id="events-sub-url-hint" className="text-xs text-muted-foreground">
          {t(copy.form.url_hint)}
        </p>
      </div>
      <div className="space-y-1">
        <Label htmlFor="events-sub-label">{t(copy.form.label)}</Label>
        <Input
          id="events-sub-label"
          required
          maxLength={100}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
      </div>
      <div className="flex flex-wrap gap-3">
        <div className="space-y-1">
          <Label htmlFor="events-sub-color">{t(copy.form.color)}</Label>
          <Input
            id="events-sub-color"
            value={color}
            pattern="#[0-9a-fA-F]{6}"
            placeholder="#2563eb"
            onChange={(e) => setColor(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="events-sub-minutes">{t(copy.form.refresh_minutes)}</Label>
          <Input
            id="events-sub-minutes"
            type="number"
            min={15}
            max={1440}
            value={minutes}
            placeholder={t(copy.form.refresh_default, { minutes: defaultMinutes })}
            onChange={(e) => setMinutes(e.target.value)}
          />
        </div>
      </div>
      <div className="space-y-1">
        <label className="flex items-center gap-2 text-sm" htmlFor="events-sub-public">
          <input
            id="events-sub-public"
            type="checkbox"
            checked={shown}
            disabled={!canShow}
            onChange={(e) => setShown(e.target.checked)}
          />
          {t(copy.form.public)}
        </label>
        <p className="text-xs text-muted-foreground">
          {!canPublish
            ? t(copy.form.public_needs_publish)
            : !isPublicCalendar
              ? t(copy.form.public_needs_public_calendar)
              : t(copy.form.public_hint)}
        </p>
      </div>
      {error ? (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={pending}>
          {t(pending ? keys.events.common.saving : keys.events.common.save)}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t(keys.events.common.cancel)}
        </Button>
      </div>
    </form>
  );
}
