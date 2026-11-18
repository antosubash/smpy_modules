/** What a refused or failed calendar write says, and whether the grid must refresh.
 *  Calendar-specific wording (a drag has no form to point at) sits on top of `errorText`. */
import { ApiError, errorText, isGone, isOrphaning, isStale } from '../../utils/api';
import { keys, translate as t } from '../../utils/i18n';
import type { Refusal } from './writes';

export type Failure = {
  message: string;
  /** The input of the Move dialog the refusal belongs to, when the server named one. */
  field?: 'start' | 'end';
  /** Where the user can fix what the grid cannot (the editor), when that helps. */
  link?: string;
  /** The grid showed something that is no longer true: refetch the range. */
  refresh: boolean;
  /** The user declined (the scope prompt, the orphans confirm): nothing to say. */
  silent?: boolean;
};

/** The user closed a prompt: the move is cancelled, with no message. */
export class Cancelled extends Error {}

const copy = keys.events.calendar.writes;

/** A change the client refused before sending it. */
export function refusalFailure(code: Refusal, zone: string): Failure {
  if (code === 'stale') return { message: t(copy.stale), refresh: true };
  if (code === 'repeated_local_time') {
    return { message: t(copy.repeated_local_time, { zone }), refresh: false };
  }
  return { message: t(keys.events.errors.invalid_local_time), refresh: false };
}

const fieldOf = (error: ApiError): Failure['field'] => {
  const name = error.field?.split('.').at(-1);
  return name === 'start' || name === 'end' ? name : undefined;
};

export function describeFailure(error: unknown, editor: { url: string; eventId: string }): Failure {
  if (error instanceof Cancelled) return { message: '', refresh: false, silent: true };
  if (isStale(error)) return { message: t(copy.stale), refresh: true };
  if (isGone(error)) return { message: t(keys.events.errors.event_gone), refresh: true };
  if (error instanceof ApiError) {
    const field = fieldOf(error);
    if (error.code === 'start_not_in_rule') {
      return {
        message: t(copy.not_in_rule),
        link: `${editor.url}/${editor.eventId}`,
        refresh: false,
      };
    }
    // A 409 that is not a stale one (`overrides_orphaned` the confirm could not resolve) and
    // everything else: the grid is still right, only the move failed.
    return { message: errorText(error), field, refresh: isOrphaning(error) };
  }
  return { message: errorText(error), refresh: false };
}
