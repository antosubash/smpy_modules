import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useId, useState } from 'react';
import { keys, useT } from '../utils/i18n';
import type { Property, PropertyInput } from '../utils/types';

const UTM = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'];
const lines = (text: string) =>
  text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);

export function PropertyEditor({
  property,
  onSave,
  onCancel,
}: {
  property?: Property;
  onSave: (input: PropertyInput) => Promise<void>;
  onCancel: () => void;
}) {
  const { t } = useT();
  const id = useId();
  const [name, setName] = useState(property?.name ?? '');
  const [kind, setKind] = useState<'public' | 'application'>(property?.kind ?? 'public');
  const [origins, setOrigins] = useState(property?.origins.join('\n') ?? window.location.origin);
  const [routes, setRoutes] = useState(property?.route_patterns.join('\n') ?? '');
  const [events, setEvents] = useState(
    Object.entries(property?.event_allowlist ?? {})
      .map(([event, fields]) => `${event}: ${fields.join(', ')}`)
      .join('\n'),
  );
  const [utm, setUtm] = useState(property?.utm_parameters ?? []);
  const [enabled, setEnabled] = useState(property?.enabled ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError('');
    const allowlist: Record<string, string[]> = {};
    for (const line of lines(events)) {
      const [eventName, fields, extra] = line.split(':');
      if (!eventName.trim() || fields === undefined || extra !== undefined) {
        setError(t(keys.analytics.event_format_error));
        return;
      }
      allowlist[eventName.trim()] = fields
        .split(',')
        .map((field) => field.trim())
        .filter(Boolean);
    }
    setBusy(true);
    try {
      await onSave({
        name,
        kind,
        origins: lines(origins),
        route_patterns: lines(routes),
        event_allowlist: allowlist,
        utm_parameters: utm,
        enabled,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t(keys.analytics.error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="rounded-lg border bg-card p-5" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className="mb-4 text-lg font-semibold">
        {t(property ? keys.analytics.edit_property : keys.analytics.new_property)}
      </h2>
      <form onSubmit={submit} className="space-y-5">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor={`${id}-name`}>{t(keys.analytics.name)}</Label>
            <Input
              id={`${id}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={100}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${id}-kind`}>{t(keys.analytics.kind)}</Label>
            <select
              id={`${id}-kind`}
              value={kind}
              onChange={(e) => setKind(e.target.value as typeof kind)}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
            >
              <option value="public">{t(keys.analytics.public)}</option>
              <option value="application">{t(keys.analytics.application)}</option>
            </select>
          </div>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor={`${id}-origins`}>{t(keys.analytics.origins)}</Label>
            <Textarea
              id={`${id}-origins`}
              value={origins}
              onChange={(e) => setOrigins(e.target.value)}
              rows={3}
              required
              aria-describedby={`${id}-origins-help`}
            />
            <p id={`${id}-origins-help`} className="text-sm text-muted-foreground">
              {t(keys.analytics.origins_help)}
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${id}-routes`}>{t(keys.analytics.routes)}</Label>
            <Textarea
              id={`${id}-routes`}
              value={routes}
              onChange={(e) => setRoutes(e.target.value)}
              rows={3}
              aria-describedby={`${id}-routes-help`}
            />
            <p id={`${id}-routes-help`} className="text-sm text-muted-foreground">
              {t(keys.analytics.routes_help)}
            </p>
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${id}-events`}>{t(keys.analytics.events_config)}</Label>
          <Textarea
            id={`${id}-events`}
            value={events}
            onChange={(e) => setEvents(e.target.value)}
            rows={3}
            aria-describedby={`${id}-events-help`}
          />
          <p id={`${id}-events-help`} className="text-sm text-muted-foreground">
            {t(keys.analytics.events_help)}
          </p>
        </div>
        <fieldset className="space-y-2">
          <legend className="mb-2 text-sm font-medium">{t(keys.analytics.utm)}</legend>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {UTM.map((param) => (
              <label key={param} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={utm.includes(param)}
                  onChange={(e) =>
                    setUtm(e.target.checked ? [...utm, param] : utm.filter((v) => v !== param))
                  }
                />
                {param}
              </label>
            ))}
          </div>
          <p className="text-sm text-muted-foreground">{t(keys.analytics.utm_help)}</p>
        </fieldset>
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            {t(keys.analytics.enabled)}
          </label>
          <p className="text-sm text-muted-foreground">{t(keys.analytics.enabled_help)}</p>
        </div>
        <div className="flex gap-2">
          <Button type="submit" disabled={busy}>
            {t(busy ? keys.analytics.saving : keys.analytics.save)}
          </Button>
          <Button type="button" variant="outline" disabled={busy} onClick={onCancel}>
            {t(keys.analytics.cancel)}
          </Button>
        </div>
      </form>
    </section>
  );
}
