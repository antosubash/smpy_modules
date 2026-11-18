/** Everything a drag, a resize or the Move dialog does to the server, in one place:
 *  read the event, stop if it changed, ask "this one or all" for a series, plan the write
 *  (`writes.ts`), send it, and turn every outcome into a message and a revert.
 *
 *  Writes on one event run one at a time. A completion that arrives after the calendar was
 *  closed changes no state and shows no toast. */
import { type ReactNode, useCallback, useRef, useState } from 'react';
import { toast } from 'sonner';
import { OrphanDialog } from '../../components/editor/OrphanDialog';
import { useRequestScope } from '../../hooks/useRequestScope';
import { isOrphaning } from '../../utils/api';
import { getEvent, previewRecurrence, setOverride, updateEvent } from '../../utils/api-events';
import { keys, translate as t } from '../../utils/i18n';
import type { EventDetail, Override } from '../../utils/types-events';
import type { Occurrence, OccurrenceChange } from '../types';
import { Cancelled, describeFailure, type Failure, refusalFailure } from './failure';
import { ScopePrompt } from './ScopePrompt';
import { isSeries, isStale, type Plan, planChange, type Scope } from './writes';

export type WriteResult = { ok: true } | ({ ok: false } & Failure);
type Ask<T> = { value: T; resolve: (answer: boolean | Scope | null) => void };

const copy = keys.events.calendar.writes;

export function useCalendarWrites({
  invalidate,
  editorUrl,
  focusEvent,
}: {
  invalidate: () => void;
  editorUrl: string;
  /** Put focus back on an event's element once a prompt closes. */
  focusEvent?: (key: string) => void;
}) {
  const begin = useRequestScope(true);
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [scopeAsk, setScopeAsk] = useState<Ask<Occurrence> | null>(null);
  const [orphanAsk, setOrphanAsk] = useState<Ask<{ orphans: Override[]; zone: string }> | null>(
    null,
  );
  const queue = useRef(new Map<string, Promise<unknown>>());

  const mark = (key: string, on: boolean) =>
    setPending((now) => {
      const next = new Set(now);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  /** Open a prompt and wait for its answer. */
  function ask<T>(open: (ask: Ask<T>) => void, value: T): Promise<boolean | Scope | null> {
    return new Promise((resolve) => open({ value, resolve }));
  }

  async function dispatch(plan: Plan): Promise<void> {
    if (plan.kind === 'patch') await updateEvent(plan.eventId, plan.body);
    else if (plan.kind === 'override') await setOverride(plan.eventId, plan.body);
  }

  /** The write, with one detour: a series shift that would orphan overrides asks first. */
  async function send(plan: Plan, event: EventDetail, signal: AbortSignal): Promise<void> {
    try {
      await dispatch(plan);
    } catch (error) {
      if (plan.kind !== 'patch' || !isOrphaning(error)) throw error;
      const found = await previewRecurrence(
        { times: plan.body.times, rrule: event.rrule, event_id: event.id },
        signal,
      );
      if (found.orphaned.length === 0) throw error;
      const sure = await ask(setOrphanAsk, { orphans: found.orphaned, zone: event.timezone });
      if (!sure) throw new Cancelled();
      await dispatch({ ...plan, body: { ...plan.body, drop_orphaned_overrides: true } });
    }
  }

  async function execute(
    change: OccurrenceChange,
    chosen: Scope | undefined,
    signal: AbortSignal,
  ): Promise<WriteResult> {
    const o = change.occurrence;
    const editor = { url: editorUrl, eventId: o.event_id ?? '' };
    try {
      if (!o.event_id) return { ok: false, ...refusalFailure('stale', o.timezone) };
      const event = await getEvent(o.event_id, undefined, signal);
      if (isStale(o, event)) return { ok: false, ...refusalFailure('stale', event.timezone) };
      let scope = chosen;
      if (isSeries(o) && !scope) {
        const answer = await ask(setScopeAsk, o);
        if (!answer) throw new Cancelled();
        scope = answer as Scope;
      }
      const plan = planChange(change, event, scope ?? 'one');
      if (plan.kind === 'refuse')
        return { ok: false, ...refusalFailure(plan.code, event.timezone) };
      await send(plan, event, signal);
      return { ok: true };
    } catch (error) {
      return { ok: false, ...describeFailure(error, editor) };
    }
  }

  /** One at a time per event: the second write reads the event the first one left. */
  function enqueue<T>(eventId: string, task: () => Promise<T>): Promise<T> {
    const before = queue.current.get(eventId) ?? Promise.resolve();
    const run = before.then(task, task);
    const tail = run.catch(() => undefined);
    queue.current.set(eventId, tail);
    void tail.then(() => queue.current.get(eventId) === tail && queue.current.delete(eventId));
    return run;
  }

  /** One write from start to finish. `report` shows a failure as a toast; the Move dialog
   *  reports it itself and gets the result back. */
  async function perform(
    change: OccurrenceChange,
    scope: Scope | undefined,
    report: boolean,
  ): Promise<WriteResult> {
    const request = begin();
    const key = change.occurrence.key;
    mark(key, true);
    const result = await enqueue(change.occurrence.event_id ?? key, () =>
      execute(change, scope, request.signal),
    );
    if (!request.alive()) return result;
    mark(key, false);
    if (result.ok) {
      toast.success(t(change.kind === 'resize' ? copy.resized : copy.moved));
      invalidate();
    } else if (!result.silent) {
      if (report) showToast(result);
      if (result.refresh) invalidate();
    }
    return result;
  }

  function showToast(failure: Failure) {
    toast.error(
      failure.link ? (
        <span>
          {failure.message}{' '}
          <a className="underline" href={failure.link}>
            {t(copy.open_editor)}
          </a>
        </span>
      ) : (
        failure.message
      ),
    );
  }

  // The two entry points are stable, so the grid's event inputs are not rebuilt on every
  // render; they always run the latest `perform`.
  const latest = useRef(perform);
  latest.current = perform;
  /** The grid's `CalendarEditing.onChange`: `false` reverts the optimistic move. */
  const onChange = useCallback(
    async (change: OccurrenceChange): Promise<boolean> =>
      (await latest.current(change, undefined, true)).ok,
    [],
  );
  /** The Move dialog's write: the scope is already chosen, and a refusal comes back to the
   *  dialog instead of a toast. */
  const submit = useCallback(
    (change: OccurrenceChange, scope?: Scope): Promise<WriteResult> =>
      latest.current(change, scope, false),
    [],
  );

  const answer = (current: Ask<unknown> | null, value: boolean | Scope | null) => {
    current?.resolve(value);
  };
  const dialogs: ReactNode = (
    <>
      <ScopePrompt
        occurrence={scopeAsk?.value ?? null}
        onChoose={(scope) => {
          answer(scopeAsk, scope);
          setScopeAsk(null);
        }}
        onClosed={(o) => focusEvent?.(o.key)}
      />
      <OrphanDialog
        orphans={orphanAsk?.value.orphans ?? null}
        timezone={orphanAsk?.value.zone ?? 'UTC'}
        onConfirm={() => {
          answer(orphanAsk, true);
          setOrphanAsk(null);
        }}
        onCancel={() => {
          answer(orphanAsk, false);
          setOrphanAsk(null);
        }}
      />
    </>
  );
  return { onChange, submit, pendingKeys: pending, dialogs };
}
