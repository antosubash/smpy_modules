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
import { changesSchedule, times, toCreate, toPatch } from '../utils/event-form';
import { FIELDS, TEXT_FIELDS, TEXT_PATH, validate } from '../utils/event-validation';
import { codeFieldPath } from '../utils/field-errors';
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
    incomplete = false,
    allowLeave,
  }: {
    calendarId: string;
    parentId: string | null;
    defaultLocale: string;
    incomplete?: boolean;
    /** Called before the page moves on after a create, so the unsaved-changes guard stays quiet. */
    allowLeave?: () => void;
  },
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

  /** Someone else saved first: their version becomes the base, with the
   *  user's own edits (since the version they began from) laid on top. */
  async function openConflict(request: ScopedRequest) {
    const started = ev.latest.current.base;
    const theirs = await ev.fetchEvent(request);
    if (!request.alive()) return;
    if (ev.rebase(theirs, started)) setConflict(true);
    else setNotice(t(keys.events.errors.stale_reloaded));
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
    setConflict(false);
    toast.success(t(keys.events.editor.saved));
  }

  async function save(drop = false, resolving = false) {
    if (saving || (conflict && !drop && !resolving)) return;
    errors.reset();
    setNotice(null);
    const found = validate(ev.form, defaultLocale, incomplete);
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
        if (request.alive()) {
          allowLeave?.();
          // The saved event takes the blank form's place, so Back goes where the user came from.
          router.visit(`/admin/events/edit/${created.id}`, { replace: true });
        }
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
    const started = ev.latest.current.form;
    const startedJson = JSON.stringify(started);
    /** Their answer replaces the form only while the form is still what the
     *  action started from. Edits typed meanwhile are kept: after an action that
     *  went through only the server-owned parts (status, revision, publish times)
     *  move; after a refused (stale) one the conflict panel opens, with the
     *  newer version as the base and the typed edits laid on top of it. */
    const take = (next: EventDetail, stale = false) => {
      const now = ev.latest.current;
      const untouched =
        JSON.stringify(now.form) === startedJson && JSON.stringify(now.base) === startedJson;
      if (untouched) {
        ev.adopt(next);
        if (stale) setNotice(t(keys.events.errors.stale_reloaded));
      } else if (!stale) {
        ev.rebase(next);
        setNotice(t(keys.events.errors.edited_meanwhile));
      } else if (ev.rebase(next, started)) {
        setConflict(true);
        setNotice(t(keys.events.errors.action_stale));
      } else {
        ev.adopt(next);
        setNotice(t(keys.events.errors.stale_reloaded));
      }
    };
    setBusy(true);
    setNotice(null);
    try {
      const result = await call(event.revision);
      if (!request.alive()) return 'handled';
      take(result ?? (await ev.fetchEvent(request)));
      if (!request.alive()) return 'handled';
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
          if (request.alive()) take(theirs, true);
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
    /** Refused while the conflict panel is open: the user chooses to load theirs or save mine. */
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
    saveMine: () => save(false, true),
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
