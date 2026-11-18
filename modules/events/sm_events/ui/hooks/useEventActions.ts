import { router } from '@inertiajs/react';
import { useCallback, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { ApiError, errorText, isGone, isOrphaning, isStale } from '../utils/api';
import {
  clearOverride,
  createEvent,
  previewRecurrence,
  setOverride,
  transition,
  updateEvent,
} from '../utils/api-events';
import { changesSchedule, type FormState, times, toCreate, toPatch } from '../utils/event-form';
import { codeFieldPath, requiredText } from '../utils/field-errors';
import { keys, translate as t } from '../utils/i18n';
import type {
  EventDetail,
  Override,
  OverrideInput,
  WorkflowAction,
  WorkflowBody,
} from '../utils/types-events';
import type { EventState } from './useEvent';
import { useFormErrors } from './useFormErrors';
import { type ScopedRequest, useRequestScope } from './useRequestScope';

/** `ok` and `handled` (a conflict or a missing event, already on screen) close a
 *  dialog; `failed` leaves it open with its own message. */
export type Outcome = 'ok' | 'failed' | 'handled';
const FIELDS = [
  'times.start',
  'times.end',
  'times.timezone',
  'rrule',
  'category_id',
  'online_url',
  'registration_url',
  'image',
  'latitude',
  'longitude',
  'venue_name',
  'organiser',
  'address',
];
const TEXT_FIELDS = ['title', 'slug', 'summary', 'seo_title', 'seo_description'];
const TEXT_PATH = /^texts\.([^.]+)\./;

function validate(form: FormState, defaultLocale: string): Record<string, string> {
  const found: Record<string, string> = {};
  for (const [locale, text] of Object.entries(form.texts)) {
    if ((text.present || locale === defaultLocale) && !text.title.trim()) {
      found[`texts.${locale}.title`] = requiredText();
    }
  }
  if (!form.start) found['times.start'] = requiredText();
  if (!form.end) found['times.end'] = requiredText();
  if (!form.timezone.trim()) found['times.timezone'] = requiredText();
  return found;
}

/** Everything the editor does to the server: save (create or update, with the
 *  conflict and orphaned-override paths), workflow and override calls. Every
 *  write quotes the event's revision; a stale one loads the newer event and
 *  never retries on its own. Each completion checks its request is still wanted. */
export function useEventActions(
  ev: EventState,
  {
    calendarId,
    parentId,
    defaultLocale,
  }: { calendarId: string; parentId: string | null; defaultLocale: string },
) {
  const locales = useMemo(() => Object.keys(ev.form.texts), [ev.form.texts]);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [orphans, setOrphans] = useState<Override[] | null>(null);
  const begin = useRequestScope(true);

  const shown = useMemo(
    () => [...FIELDS, ...locales.flatMap((l) => TEXT_FIELDS.map((f) => `texts.${l}.${f}`))],
    [locales],
  );
  const slugLocales = locales.filter(
    (l) =>
      ev.form.texts[l]?.present &&
      ev.form.texts[l]?.slug &&
      ev.form.texts[l]?.slug !== ev.base.texts[l]?.slug,
  );
  const codeField = useCallback(
    (e: unknown) => codeFieldPath(e, { defaultLocale, slugLocales }),
    [defaultLocale, slugLocales],
  );
  const errors = useFormErrors(keys.events.errors.event_gone, ev.markGone, shown, codeField);

  /** Show the language the failure is in, in the same render the message appears. */
  function fail(e: unknown) {
    const path =
      codeField(e) ?? (e instanceof ApiError ? e.fields.find((f) => TEXT_PATH.test(f)) : undefined);
    const locale = path ? TEXT_PATH.exec(path)?.[1] : undefined;
    if (locale && locales.includes(locale)) ev.setTab(locale);
    errors.fail(e);
  }

  /** Someone else saved first: load their version as the base, keep the form. */
  async function openConflict(request: ScopedRequest) {
    const theirs = await ev.fetchEvent(request);
    if (!request.alive()) return;
    ev.rebase(theirs);
    setConflict(true);
  }

  async function writeExisting(event: EventDetail, drop: boolean, request: ScopedRequest) {
    const patch = toPatch(ev.base, ev.form, event.revision);
    if (!patch) return;
    if (!drop && changesSchedule(ev.base, ev.form) && event.overrides.length > 0) {
      const found = await previewRecurrence({
        times: times(ev.form),
        rrule: ev.form.rrule || null,
        event_id: event.id,
      });
      if (!request.alive()) return;
      if (found.orphaned.length > 0) return setOrphans(found.orphaned);
    }
    if (drop) patch.drop_orphaned_overrides = true;
    const next = await updateEvent(event.id, patch);
    if (!request.alive()) return;
    ev.adopt(next);
    toast.success(t(keys.events.editor.saved));
  }

  async function save(drop = false) {
    if (saving) return;
    errors.reset();
    setNotice(null);
    const found = validate(ev.form, defaultLocale);
    if (Object.keys(found).length > 0) {
      const locale = TEXT_PATH.exec(Object.keys(found).find((f) => TEXT_PATH.test(f)) ?? '')?.[1];
      if (locale) ev.setTab(locale);
      errors.reject(found);
      return;
    }
    const request = begin();
    setSaving(true);
    try {
      if (ev.event) {
        await writeExisting(ev.event, drop, request);
      } else {
        const body = {
          ...toCreate(ev.form, calendarId),
          ...(parentId ? { parent_id: parentId } : {}),
        };
        const created = await createEvent(body);
        if (request.alive()) router.visit(`/admin/events/edit/${created.id}`);
      }
    } catch (e) {
      if (!request.alive()) return;
      await failed(e, request);
    } finally {
      if (request.alive()) setSaving(false);
    }
  }
  async function failed(e: unknown, request: ScopedRequest) {
    try {
      if (isStale(e)) return await openConflict(request);
      if (isOrphaning(e) && ev.event) {
        const found = await previewRecurrence({
          times: times(ev.form),
          rrule: ev.form.rrule || null,
          event_id: ev.event.id,
        });
        if (request.alive() && found.orphaned.length > 0) return setOrphans(found.orphaned);
      }
    } catch (inner) {
      if (!request.alive()) return;
      if (isGone(inner)) return ev.markGone();
      return fail(inner);
    }
    fail(e);
  }

  /** A write that is not the form's: quote the revision, then show the result.
   *  A conflict reloads the event, which is safe because these need a clean form. */
  async function run(
    call: (revision: number) => Promise<EventDetail | undefined>,
    onError?: (e: unknown) => void,
  ): Promise<Outcome> {
    const event = ev.event;
    if (!event || busy) return 'handled';
    const request = begin();
    setBusy(true);
    setNotice(null);
    try {
      const result = await call(event.revision);
      if (!request.alive()) return 'handled';
      if (result) ev.adopt(result);
      else await ev.reload();
      return 'ok';
    } catch (e) {
      if (!request.alive()) return 'handled';
      if (isGone(e)) {
        ev.markGone();
        return 'handled';
      }
      if (isStale(e)) {
        try {
          const theirs = await ev.fetchEvent(request);
          if (request.alive()) {
            ev.adopt(theirs);
            setNotice(t(keys.events.errors.stale_reloaded));
          }
        } catch (inner) {
          if (request.alive()) setNotice(errorText(inner));
        }
        return 'handled';
      }
      if (onError) onError(e);
      else setNotice(errorText(e));
      return 'failed';
    } finally {
      if (request.alive()) setBusy(false);
    }
  }

  return {
    errors,
    saving,
    busy,
    notice,
    conflict,
    orphans,
    save: () => save(false),
    confirmOrphans: () => {
      setOrphans(null);
      return save(true);
    },
    cancelOrphans: () => setOrphans(null),
    loadTheirs: () => {
      setConflict(false);
      if (ev.event) ev.adopt(ev.event);
    },
    saveMine: () => {
      setConflict(false);
      return save(false);
    },
    transition: (
      action: WorkflowAction,
      body: Omit<WorkflowBody, 'expected_revision'> = {},
      onError?: (e: unknown) => void,
    ) =>
      run(
        (revision) =>
          transition(ev.event?.id ?? '', action, { ...body, expected_revision: revision }),
        onError,
      ),
    setOverride: (
      input: Omit<OverrideInput, 'expected_revision'>,
      onError?: (e: unknown) => void,
    ) =>
      run(async (revision) => {
        await setOverride(ev.event?.id ?? '', { ...input, expected_revision: revision });
        return undefined;
      }, onError),
    clearOverride: (id: number) =>
      run(async (revision) => {
        await clearOverride(ev.event?.id ?? '', id, revision);
        return undefined;
      }),
  };
}
