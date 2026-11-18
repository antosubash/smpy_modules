/** Which plugin sources a calendar shows, and their settings. Opened by whoever may change the
 *  calendar's visibility (the server enforces it too). Every installed source can be enabled; its
 *  module's own settings section is used when it registered one, a JSON editor otherwise. An entry
 *  no module on this server provides is listed as "not installed", kept on save, and removable
 *  after a confirmation. Settings are never secret: the server refuses secret-typed fields. */
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useEventExtensions } from '../../extensions/load';
import { PluginBoundary } from '../../extensions/PluginBoundary';
import { source as registered } from '../../extensions/registry';
import { translateKey } from '../../extensions/translateKey';
import { useGoneOnce, useRequestScope } from '../../hooks/useRequestScope';
import { ApiError, errorText, isGone, isStale } from '../../utils/api';
import {
  listSources,
  putCalendarSources,
  type SourceEntryInput,
  type SourceInfo,
} from '../../utils/api-extensions';
import { keys, useT } from '../../utils/i18n';
import { Name, withName } from '../../utils/isolate';
import type { Calendar, CalendarSource } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { JsonSettings } from './JsonSettings';

type Settings = Record<string, unknown>;
type Errors = Record<string, Record<string, string>>;

/** `sources.<i>.settings.<path>` messages, grouped by the source sent at index `i`. */
function groupErrors(error: unknown, sent: readonly SourceEntryInput[]): Errors {
  const out: Errors = {};
  if (!(error instanceof ApiError) || error.status !== 422) return out;
  for (const [path, message] of Object.entries(error.messages)) {
    const [head, index, settings, ...rest] = path.split('.');
    const id = head === 'sources' && settings === 'settings' ? sent[Number(index)]?.id : undefined;
    if (!id) continue;
    const mine = out[id] ?? {};
    mine[rest.join('.')] = message;
    out[id] = mine;
  }
  return out;
}

export function SourcesDialog({ calendar, onSaved }: { calendar: Calendar; onSaved: () => void }) {
  const { t } = useT();
  const copy = keys.events.sources;
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState<SourceInfo[] | null>(null);
  const [enabled, setEnabled] = useState<Record<string, Settings>>({});
  const [kept, setKept] = useState<CalendarSource[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [invalid, setInvalid] = useState<ReadonlySet<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  useEventExtensions(); // this screen has no calendar to load the plugins; they are lazy
  const gone = useGoneOnce(open, onSaved);
  const begin = useRequestScope(open);

  // The form starts from the calendar as it was when the dialog opened; a reload behind it (after
  // a stale refusal) must not wipe the message or the user's edits.
  const latest = useRef(calendar);
  latest.current = calendar;
  const reset = useCallback(() => {
    const stored = latest.current.sources;
    setEnabled(
      Object.fromEntries(stored.filter((s) => s.installed).map((s) => [s.id, s.settings])),
    );
    setKept(stored.filter((s) => !s.installed));
    setErrors({});
    setInvalid(new Set());
    setError(null);
  }, []);

  useEffect(() => {
    if (!open) return;
    reset();
    const request = begin();
    listSources(request.signal)
      .then((list) => request.alive() && setAvailable(list))
      .catch((e: unknown) => request.alive() && setError(errorText(e)));
  }, [open, reset, begin]);

  const sent = (): SourceEntryInput[] => [
    ...(available ?? [])
      .filter((s) => s.id in enabled)
      .map((s) => ({ id: s.id, settings: enabled[s.id] ?? {} })),
    ...kept.map((s) => ({ id: s.id, settings: s.settings })),
  ];

  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending || invalid.size > 0) return;
    const entries = sent();
    const request = begin();
    setPending(true);
    setError(null);
    setErrors({});
    try {
      await putCalendarSources(calendar.id, entries, calendar.sources_version);
      if (!request.alive()) return;
      onSaved();
      setOpen(false);
    } catch (e) {
      if (!request.alive()) return;
      if (isStale(e)) {
        setError(t(copy.stale));
        onSaved();
      } else {
        const grouped = groupErrors(e, entries);
        setErrors(grouped);
        setError(
          Object.keys(grouped).length ? null : errorText(e, keys.events.errors.calendar_gone),
        );
      }
      if (isGone(e)) gone();
    } finally {
      if (request.alive()) setPending(false);
    }
  }

  const setSettings = (id: string, next: Settings | null) => {
    setInvalid((now) => {
      const copyOf = new Set(now);
      if (next === null) copyOf.add(id);
      else copyOf.delete(id);
      return copyOf;
    });
    if (next !== null) setEnabled((now) => ({ ...now, [id]: next }));
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) setOpen(next);
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" aria-label={t(copy.trigger_for, { name: calendar.name })}>
          {t(copy.trigger)}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{withName(t, copy.title, calendar.name)}</DialogTitle>
          <DialogDescription>{t(copy.description)}</DialogDescription>
        </DialogHeader>
        <form onSubmit={save} noValidate className="grid gap-4">
          {available === null && !error ? <p role="status">{t(copy.loading)}</p> : null}
          {available?.length === 0 && kept.length === 0 ? <p>{t(copy.none)}</p> : null}
          <ul className="grid gap-4">
            {(available ?? []).map((info) => {
              const label = translateKey(t, info.label_key, info.id);
              const on = info.id in enabled;
              const Section = registered(info.id)?.SettingsSection;
              return (
                <li key={info.id} className="grid gap-2 rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      id={`source-${info.id}`}
                      type="checkbox"
                      className="size-4 accent-primary"
                      checked={on}
                      onChange={() =>
                        setEnabled((now) => {
                          if (info.id in now) {
                            const { [info.id]: _off, ...rest } = now;
                            return rest;
                          }
                          return { ...now, [info.id]: {} };
                        })
                      }
                    />
                    <label htmlFor={`source-${info.id}`} className="font-medium">
                      <Name>{label}</Name>
                    </label>
                    {info.public ? (
                      <Badge
                        variant="outline"
                        data-testid="source-public"
                        title={t(copy.public_hint)}
                      >
                        {t(copy.public)}
                      </Badge>
                    ) : null}
                  </div>
                  {on && info.has_settings ? (
                    Section ? (
                      <PluginBoundary
                        name={`${info.id}/settings`}
                        fallback={
                          <JsonSettings
                            id={`json-${info.id}`}
                            settings={enabled[info.id] ?? {}}
                            errors={errors[info.id] ?? {}}
                            onChange={(next) => setSettings(info.id, next)}
                          />
                        }
                      >
                        <Section
                          settings={enabled[info.id] ?? {}}
                          onChange={(next) => setSettings(info.id, next)}
                          errors={errors[info.id] ?? {}}
                          calendar={{
                            id: calendar.id,
                            name: calendar.name,
                            default_timezone: calendar.default_timezone,
                          }}
                        />
                      </PluginBoundary>
                    ) : (
                      <JsonSettings
                        id={`json-${info.id}`}
                        settings={enabled[info.id] ?? {}}
                        errors={errors[info.id] ?? {}}
                        onChange={(next) => setSettings(info.id, next)}
                      />
                    )
                  ) : null}
                </li>
              );
            })}
            {kept.map((entry) => (
              <li key={entry.id} className="grid gap-2 rounded-md border border-dashed p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    <Name>{entry.id}</Name>
                  </span>
                  <Badge variant="outline">{t(copy.not_installed)}</Badge>
                  <ConfirmDialog
                    trigger={
                      <Button type="button" variant="outline" size="sm">
                        {t(copy.remove)}
                      </Button>
                    }
                    title={withName(t, copy.remove_title, entry.id)}
                    description={t(copy.remove_description)}
                    confirmLabel={t(copy.remove)}
                    onConfirm={async () => setKept((now) => now.filter((k) => k.id !== entry.id))}
                  />
                </div>
                <p className="text-sm text-muted-foreground">{t(copy.not_installed_hint)}</p>
              </li>
            ))}
          </ul>
          {error ? (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => setOpen(false)}
            >
              {t(keys.events.common.cancel)}
            </Button>
            <Button type="submit" disabled={pending || invalid.size > 0}>
              {pending ? t(keys.events.common.saving) : t(keys.events.common.save)}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
