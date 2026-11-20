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
import { useGoneOnce, useRequestScope } from '../../hooks/useRequestScope';
import { errorText, isGone, isStale } from '../../utils/api';
import {
  listSources,
  putCalendarSources,
  type SourceEntryInput,
  type SourceInfo,
} from '../../utils/api-extensions';
import { keys, useT } from '../../utils/i18n';
import { withName } from '../../utils/isolate';
import type { Calendar, CalendarSource } from '../../utils/types';
import { KeptSourceRow, SourceRow } from './SourceRow';
import { type Errors, groupErrors, storedProblems } from './sourceProblems';

type Settings = Record<string, unknown>;
export function SourcesDialog({ calendar, onSaved }: { calendar: Calendar; onSaved: () => void }) {
  const { t } = useT();
  const copy = keys.events.sources;
  const [open, setOpen] = useState(false);
  const [available, setAvailable] = useState<SourceInfo[] | null>(null);
  const [enabled, setEnabled] = useState<Record<string, Settings>>({});
  const [kept, setKept] = useState<CalendarSource[]>([]);
  const [errors, setErrors] = useState<Errors>({});
  const [codes, setCodes] = useState<Errors>({});
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
    const known = storedProblems(stored);
    setErrors(known.errors);
    setCodes(known.codes);
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
    setCodes({});
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
        setErrors(grouped.errors);
        setCodes(grouped.codes);
        setError(
          Object.keys(grouped.errors).length
            ? null
            : errorText(e, keys.events.errors.calendar_gone),
        );
      }
      if (isGone(e)) gone();
    } finally {
      if (request.alive()) setPending(false);
    }
  }

  const toggleSource = (id: string) =>
    setEnabled((now) => {
      if (id in now) {
        const { [id]: _off, ...rest } = now;
        return rest;
      }
      return { ...now, [id]: {} };
    });

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
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
        showCloseButton={false}
        // The sources load after the dialog opens, so the first tabbable thing at that moment is
        // Cancel: start on the dialog itself and the first Tab reaches the first source.
        onOpenAutoFocus={(e) => {
          e.preventDefault();
          (e.currentTarget as HTMLElement).focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>{withName(t, copy.title, calendar.name)}</DialogTitle>
          <DialogDescription>{t(copy.description)}</DialogDescription>
        </DialogHeader>
        <form onSubmit={save} noValidate className="grid gap-4">
          {available === null && !error ? <p role="status">{t(copy.loading)}</p> : null}
          {available?.length === 0 && kept.length === 0 ? <p>{t(copy.none)}</p> : null}
          <ul className="grid gap-4">
            {(available ?? []).map((info) => (
              <SourceRow
                key={info.id}
                info={info}
                settings={info.id in enabled ? (enabled[info.id] ?? {}) : null}
                errors={errors[info.id] ?? {}}
                codes={codes[info.id] ?? {}}
                calendar={calendar}
                onToggle={() => toggleSource(info.id)}
                onSettings={(next) => setSettings(info.id, next)}
              />
            ))}
            {kept.map((entry) => (
              <KeptSourceRow
                key={entry.id}
                id={entry.id}
                onRemove={() => setKept((now) => now.filter((k) => k.id !== entry.id))}
              />
            ))}
          </ul>
          {error ? (
            <p role="alert" className="text-destructive dark:text-red-400">
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
