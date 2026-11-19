/** The anonymous read behind a registration panel: one occurrence's availability and, while it is
 *  open, the form with a token bound to that event and occurrence. The event and the occurrence
 *  travel only here, in the query; the token carries them back on submit. Never cached. */
import { SUBMISSIONS_API_PREFIX, type SubmissionDefinition } from './submissions-form-api';

export type RegistrationState = 'cancelled' | 'not_open_yet' | 'closed' | 'full' | 'open';

export type RegistrationView = {
  availability: {
    state: RegistrationState;
    /** An exact number: only a double opt-in form whose event shows seats. */
    seats_left: number | null;
    /** A threshold state, for the forms that must not show a number. */
    few_left: boolean;
    opens_at: string | null;
    closes_at: string | null;
  };
  event: {
    title: string;
    when_text: string;
    venue_name: string | null;
    address: string | null;
  } | null;
  definition: SubmissionDefinition | null;
};

export type RegistrationResult =
  | { status: 'ready'; view: RegistrationView }
  | { status: 'unavailable' }
  | { status: 'error' };

export async function fetchRegistration(
  typeKey: string,
  eventId: string,
  occurrenceKey: string,
  locale: string | undefined,
  signal?: AbortSignal,
): Promise<RegistrationResult> {
  const query = new URLSearchParams({ event: eventId, occurrence: occurrenceKey });
  if (locale) query.set('locale', locale);
  try {
    const response = await fetch(
      `${SUBMISSIONS_API_PREFIX}/${encodeURIComponent(typeKey)}/registration?${query}`,
      {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        cache: 'no-store',
        signal,
      },
    );
    if (response.status === 404) return { status: 'unavailable' };
    if (!response.ok) return { status: 'error' };
    return { status: 'ready', view: (await response.json()) as RegistrationView };
  } catch (error) {
    if ((error as { name?: string })?.name === 'AbortError') throw error;
    return { status: 'error' };
  }
}
